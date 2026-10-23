"""
A download queue: installs and updates that run one after another, optionally only inside a daily time window
(e.g. overnight). Each job is its own "heirloom install" process. When the window closes, the job is stopped as
a Ctrl-C would, and the download's resume file lets the next window continue where it stopped.
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from datetime import time as daytime
from pathlib import Path
from typing import Any

import heirloom
from heirloom.lfs.utils import LockedJSONData

log = logging.getLogger('Queue')


@dataclass(frozen=True)
class TimeWindow:
    """A daily time range, which may cross midnight (e.g. 23:00-07:00)"""
    start: daytime
    end: daytime

    @classmethod
    def parse(cls, text: str) -> TimeWindow:
        try:
            start, end = (datetime.strptime(part.strip(), '%H:%M').time() for part in text.split('-'))
        except ValueError:
            raise ValueError(f'"{text}" is not a time window, use e.g. "01:00-07:00"') from None
        if start == end:
            raise ValueError(f'"{text}" is an empty time window')
        return cls(start, end)

    def __str__(self) -> str:
        return f'{self.start:%H:%M}-{self.end:%H:%M}'

    def contains(self, moment: datetime) -> bool:
        now = moment.time()
        if self.start < self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end

    def next_start(self, moment: datetime) -> datetime:
        start = datetime.combine(moment.date(), self.start)
        return start if start > moment else start + timedelta(days=1)


@dataclass
class QueuedDownload:
    app_name: str
    # extra "heirloom install" options, e.g. ["--platform", "Mac"]
    options: list[str] = field(default_factory=list)


class DownloadQueue:
    """The queued downloads in order, in a file that "queue add" and a running queue share"""

    def __init__(self, path: Path):
        self.path = path

    def jobs(self) -> list[QueuedDownload]:
        with LockedJSONData(self.path) as lock:
            return [QueuedDownload(**job) for job in lock.data or []]

    def add(self, job: QueuedDownload) -> bool:
        """Queues the job, or updates the options of the one already queued for the app. True if it is new."""
        with LockedJSONData(self.path) as lock:
            jobs = lock.data or []
            for queued in jobs:
                if queued['app_name'] == job.app_name:
                    queued['options'] = job.options
                    return False
            lock.data = [*jobs, asdict(job)]
            return True

    def remove(self, app_name: str) -> bool:
        with LockedJSONData(self.path) as lock:
            jobs = lock.data or []
            kept = [job for job in jobs if job['app_name'] != app_name]
            if kept:
                lock.data = kept
            else:
                lock.clear()
            return len(kept) < len(jobs)

    def clear(self) -> None:
        with LockedJSONData(self.path) as lock:
            lock.clear()


def heirloom_command() -> list[str]:
    """The command that starts this Heirloom again"""
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    package_parent = Path(heirloom.__file__).parent.parent
    if package_parent.is_file():
        # a zipapp, the package is inside the .pyz
        return [sys.executable, str(package_parent)]
    return [sys.executable, '-m', 'heirloom.cli']


def start_job(command: list[str], **popen_options: Any) -> subprocess.Popen:
    # in its own process group, so it can be stopped without stopping the queue; a prompt fails instead of waiting
    if sys.platform == 'win32':
        return subprocess.Popen(command, stdin=subprocess.DEVNULL, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                                **popen_options)
    return subprocess.Popen(command, stdin=subprocess.DEVNULL, start_new_session=True, **popen_options)


def interrupt_job(job: subprocess.Popen) -> None:
    """Stops the job as a Ctrl-C in its terminal would"""
    if sys.platform == 'win32':
        # Ctrl-C can't be sent to another process group, Ctrl+Break can (see handle_ctrl_break_as_ctrl_c)
        job.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        os.killpg(job.pid, signal.SIGINT)


def kill_job(job: subprocess.Popen) -> None:
    """Ends the job and every process it started, e.g. the download workers"""
    if sys.platform == 'win32':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(job.pid)], capture_output=True)
    else:
        with suppress(ProcessLookupError):
            os.killpg(job.pid, signal.SIGKILL)
    job.wait()


def stop_job(job: subprocess.Popen, seconds: float = 60.0) -> None:
    """Stops the job as a Ctrl-C would, so a download keeps its resume file; ends it if that doesn't work in time"""
    if job.poll() is not None:
        return
    try:
        interrupt_job(job)
        job.wait(timeout=seconds)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(f'The download did not stop ({e!r}), ending it.')
        kill_job(job)


def handle_ctrl_break_as_ctrl_c() -> None:
    if sys.platform == 'win32':
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


@dataclass
class QueueRun:
    done: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


class QueueRunner:
    POLL_SECONDS = 5.0
    STOP_SECONDS = 60.0

    def __init__(self, queue: DownloadQueue, window: TimeWindow | None,
                 command: Callable[[QueuedDownload], list[str]],
                 now: Callable[[], datetime] = datetime.now, sleep: Callable[[float], None] = time.sleep):
        self.queue = queue
        self.window = window
        self.command = command
        self.now = now
        self.sleep = sleep

    def run(self) -> QueueRun:
        """Runs queued downloads until none are left, except ones that failed in this run"""
        result = QueueRun()
        # the queue is read again for each job, so downloads queued meanwhile are picked up
        while job := next((job for job in self.queue.jobs() if job.app_name not in result.failed), None):
            if self.window and not self.window.contains(self.now()):
                self._wait_for_window(self.window)
                continue
            exit_code = self._run_job(job)
            if exit_code is None:
                continue
            if exit_code == 0:
                self.queue.remove(job.app_name)
                result.done.append(job.app_name)
            else:
                log.error(f'Downloading "{job.app_name}" failed (exit code {exit_code}), it stays queued.')
                result.failed.append(job.app_name)
        return result

    def _wait_for_window(self, window: TimeWindow) -> None:
        log.info(f'Waiting for the download window {window}, it opens at {window.next_start(self.now()):%H:%M}...')
        while not window.contains(now := self.now()):
            # in short steps, so a clock change or waking from sleep is noticed
            self.sleep(min(60.0, max(1.0, (window.next_start(now) - now).total_seconds())))

    def _run_job(self, job: QueuedDownload) -> int | None:
        """The job's exit code, or None if it was stopped because the window closed"""
        log.info(f'Downloading "{job.app_name}"...')
        process = start_job(self.command(job))
        try:
            while (exit_code := self._wait(process)) is None:
                if self.window and not self.window.contains(self.now()):
                    log.info(f'The download window {self.window} closed, stopping "{job.app_name}" until it opens '
                             f'again.')
                    stop_job(process, self.STOP_SECONDS)
                    return None
            return exit_code
        except BaseException:
            # e.g. a Ctrl-C of the queue: never leave a download running on its own
            stop_job(process, self.STOP_SECONDS)
            raise

    def _wait(self, process: subprocess.Popen) -> int | None:
        try:
            return process.wait(timeout=self.POLL_SECONDS)
        except subprocess.TimeoutExpired:
            return None
