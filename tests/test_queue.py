"""The download queue: time windows, the queue file, and running queued downloads as separate processes."""
import json
import sys
from datetime import datetime, timedelta

import pytest

from heirloom.downloader.queue import (
    DownloadQueue,
    QueuedDownload,
    QueueRunner,
    TimeWindow,
)

from .test_cli import run

# Stands in for "heirloom install": logs what happens to it, and stops on Ctrl-C (Ctrl+Break on Windows)
# the way heirloom does.
JOB = '''
import sys, time
from pathlib import Path
from heirloom.downloader.queue import handle_ctrl_break_as_ctrl_c

handle_ctrl_break_as_ctrl_c()
log, name, kind = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = log.read_text().splitlines() if log.exists() else []

def note(event):
    with log.open('a') as f:
        f.write(f'{name} {event}\\n')

if kind == 'fail':
    note('failed')
    sys.exit(3)
if kind == 'slow' and f'{name} stopped' not in lines:
    note('started')
    try:
        # short steps: on Windows Ctrl+Break is only handled between them, not during one long sleep
        for _ in range(300):
            time.sleep(0.1)
    except KeyboardInterrupt:
        note('stopped')
        sys.exit(0)
note('done')
'''


def at(hour, minute=0, day=23):
    return datetime(2026, 10, day, hour, minute)


@pytest.mark.parametrize(('window', 'inside', 'outside'), [
    ('01:00-07:00', [at(1), at(6, 59)], [at(0, 59), at(7), at(12)]),
    ('23:00-07:00', [at(23), at(0), at(6, 59)], [at(7), at(22, 59), at(12)]),
])
def test_time_window(window, inside, outside):
    parsed = TimeWindow.parse(window)
    assert str(parsed) == window
    assert all(parsed.contains(moment) for moment in inside)
    assert not any(parsed.contains(moment) for moment in outside)


def test_time_window_next_start():
    window = TimeWindow.parse('01:00-07:00')
    assert window.next_start(at(0, 30)) == at(1)
    assert window.next_start(at(8)) == at(1, day=24)
    assert window.next_start(at(1)) == at(1, day=24), 'an open window next opens tomorrow'


@pytest.mark.parametrize('text', ['', '1-7', '25:00-07:00', '01:00', '01:00-02:00-03:00', '07:00-07:00'])
def test_invalid_time_window(text):
    with pytest.raises(ValueError):
        TimeWindow.parse(text)


def test_queue_command(lgd_home):
    assert 'The queue is empty' in run('queue').stdout

    added = run('queue', 'add', 'Fish', 'Goo', '--platform', 'Mac', '--max-speed', '5M')
    assert added.returncode == 0, added.stderr
    assert run('queue', 'add', 'Fish', '--max-speed', '2M').returncode == 0
    assert json.loads((lgd_home / 'queue.json').read_text()) == [
        {'app_name': 'Fish', 'options': ['--max-speed', '2M']},
        {'app_name': 'Goo', 'options': ['--platform', 'Mac', '--max-speed', '5M']},
    ], 'queueing a game again updates its options instead of adding it twice'

    listed = run('queue', '--window', '23:00-07:00').stdout
    assert ' 1. Fish --max-speed 2M' in listed and ' 2. Goo --platform Mac --max-speed 5M' in listed
    assert 'Download window: 23:00-07:00' in listed

    bad_option = run('queue', 'add', 'Hat', '--no-such-option')
    assert bad_option.returncode != 0 and '--no-such-option' in bad_option.stderr
    bad_window = run('queue', 'run', '--window', '25:00-07:00')
    assert bad_window.returncode != 0 and 'is not a time window' in bad_window.stderr
    assert [job['app_name'] for job in json.loads((lgd_home / 'queue.json').read_text())] == ['Fish', 'Goo']

    removed = run('queue', 'remove', 'Goo', 'Hat')
    assert 'Removed "Goo"' in removed.stderr and '"Hat" is not queued' in removed.stderr
    run('queue', 'clear')
    assert not (lgd_home / 'queue.json').exists()


class Clock:
    """A clock for the runner that the window closes on once the slow job has started"""

    def __init__(self, log, moment):
        self.log = log
        self.moment = moment
        self.slept = timedelta()

    def now(self):
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        if 'Fish started' in lines and 'Fish stopped' not in lines:
            self.moment = at(7, 0)
        return self.moment

    def sleep(self, seconds):
        self.slept += timedelta(seconds=seconds)
        self.moment += timedelta(seconds=seconds)


def runner(tmp_path, jobs, window=None, moment=None):
    queue = DownloadQueue(tmp_path / 'queue.json')
    for name, kind in jobs:
        queue.add(QueuedDownload(name, [kind]))
    log = tmp_path / 'jobs.log'
    clock = Clock(log, moment or at(2))
    queue_runner = QueueRunner(queue, window, lambda job: [sys.executable, '-c', JOB, str(log), job.app_name,
                                                           *job.options], now=clock.now, sleep=clock.sleep)
    queue_runner.POLL_SECONDS = 0.1
    # well under the slow job's 30 seconds, so a missed interrupt ends it before it logs "stopped"
    queue_runner.STOP_SECONDS = 10
    return queue, queue_runner, log, clock


def test_runner_downloads_in_order_and_keeps_failed_ones(tmp_path):
    queue, queue_runner, log, _ = runner(tmp_path, [('Fish', 'ok'), ('Goo', 'fail'), ('Hat', 'ok')])
    result = queue_runner.run()
    assert log.read_text().splitlines() == ['Fish done', 'Goo failed', 'Hat done']
    assert (result.done, result.failed) == (['Fish', 'Hat'], ['Goo'])
    assert queue.jobs() == [QueuedDownload('Goo', ['fail'])]


def test_runner_waits_for_the_window(tmp_path):
    _, queue_runner, log, clock = runner(tmp_path, [('Fish', 'ok')], TimeWindow.parse('01:00-07:00'), at(22))
    assert queue_runner.run().done == ['Fish']
    assert clock.slept == timedelta(hours=3), 'waited from 22:00 until the window opened at 01:00'
    assert log.read_text().splitlines() == ['Fish done']


def test_runner_stops_a_download_when_the_window_closes_and_resumes_it_in_the_next(tmp_path):
    queue, queue_runner, log, clock = runner(tmp_path, [('Fish', 'slow'), ('Goo', 'ok')],
                                             TimeWindow.parse('01:00-07:00'), at(6, 59))
    result = queue_runner.run()
    assert log.read_text().splitlines() == ['Fish started', 'Fish stopped', 'Fish done', 'Goo done'], \
        'stopped as by Ctrl-C at 07:00, then continued first thing in the next window'
    assert clock.slept == timedelta(hours=18)
    assert result.done == ['Fish', 'Goo'] and not queue.jobs()
