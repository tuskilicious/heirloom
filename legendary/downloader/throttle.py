"""Download speed limits, including a lower one while a game started by "legendary launch" is running"""
from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from filelock import FileLock, Timeout

_UNITS = {'k': 1024, 'm': 1024 ** 2, 'g': 1024 ** 3}


def parse_speed(text: str) -> int:
    """
    A speed like "5", "5M", "500K" or "1.5 MiB/s" in bytes per second; plain numbers are MiB/s.
    0 means unlimited.
    """
    match = re.fullmatch(r'(\d+(?:\.\d+)?)\s*([kmg]?)(?:i?b)?(?:/s)?', text.strip().lower())
    if not match:
        raise ValueError(f'"{text}" is not a speed, use e.g. "5" or "5M" (MiB/s) or "500K" (KiB/s)')
    return int(float(match[1]) * _UNITS[match[2] or 'm'])


def format_speed(speed: int) -> str:
    return f'{speed / 1024 ** 2:.2f} MiB/s'


def games_running(folder: Path) -> bool:
    """Whether a "legendary launch" is waiting for a game, which it shows by holding a lock in the folder"""
    for lock_file in folder.glob('*.lock'):
        lock = FileLock(lock_file)
        try:
            lock.acquire(timeout=0)
        except Timeout:
            return True
        # a leftover from a launch that ended without cleaning up; the OS dropped its lock
        lock.release()
    return False


@dataclass
class SpeedLimits:
    """Limits in bytes per second, 0 for none"""
    max_speed: int = 0
    max_speed_while_playing: int = 0
    running_games_dir: str = ''

    def __bool__(self) -> bool:
        return bool(self.max_speed or self.max_speed_while_playing)

    def current(self, playing: bool) -> int:
        limits = [self.max_speed, self.max_speed_while_playing if playing else 0]
        return min((limit for limit in limits if limit), default=0)


class Throttle:
    """Paces chunk downloads so they average at most the current limit (a token bucket)"""
    BURST_SECONDS = 1.0
    CHECK_INTERVAL = 2.0

    def __init__(self, limits: SpeedLimits, clock: Callable[[], float] = time.monotonic):
        self.limits = limits
        self.clock = clock
        self.rate = 0
        self.playing = False
        self._tokens = 0.0
        self._updated = clock()
        self._checked: float | None = None

    def _refresh(self, now: float) -> None:
        if self._checked is not None and now - self._checked < self.CHECK_INTERVAL:
            return
        self._checked = now
        self.playing = bool(self.limits.max_speed_while_playing and self.limits.running_games_dir
                            and games_running(Path(self.limits.running_games_dir)))
        self.rate = self.limits.current(self.playing)

    def reserve(self, size: int) -> float:
        """Takes size bytes from the budget and returns how many seconds to wait before downloading them"""
        now = self.clock()
        self._refresh(now)
        if not self.rate:
            self._tokens, self._updated = 0.0, now
            return 0.0
        self._tokens = min(self.rate * self.BURST_SECONDS, self._tokens + (now - self._updated) * self.rate)
        self._updated = now
        self._tokens -= size
        return max(0.0, -self._tokens / self.rate)
