import json
import subprocess
import sys
import time

import pytest

from heirloom.downloader import throttle
from heirloom.downloader.throttle import (
    SpeedLimits,
    Throttle,
    games_running,
    parse_speed,
)

KiB, MiB = 1024, 1024 ** 2

HOLD_LOCK = '''
import sys
from filelock import FileLock
lock = FileLock(sys.argv[1])
lock.acquire()
print('held', flush=True)
sys.stdin.read()
'''


@pytest.mark.parametrize(('text', 'speed'), [
    ('5', 5 * MiB), ('5M', 5 * MiB), ('1.5 MiB/s', int(1.5 * MiB)), ('500K', 500 * KiB), ('500kb/s', 500 * KiB),
    ('2G', 2 * 1024 * MiB), ('0', 0), (' 10m ', 10 * MiB),
])
def test_parse_speed(text, speed):
    assert parse_speed(text) == speed


@pytest.mark.parametrize('text', ['', 'fast', '-5', '5T', '5 Mbit'])
def test_parse_speed_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_speed(text)


def test_lower_limit_applies_only_while_playing():
    limits = SpeedLimits(max_speed=10 * MiB, max_speed_while_playing=2 * MiB)
    assert (limits.current(playing=False), limits.current(playing=True)) == (10 * MiB, 2 * MiB)
    assert SpeedLimits(max_speed_while_playing=2 * MiB).current(playing=False) == 0
    assert SpeedLimits(max_speed=1 * MiB, max_speed_while_playing=2 * MiB).current(playing=True) == 1 * MiB
    assert not SpeedLimits() and SpeedLimits(max_speed_while_playing=1)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_throttle_paces_to_the_limit_with_one_second_of_burst():
    clock = Clock()
    pacer = Throttle(SpeedLimits(max_speed=1000), clock=clock)

    assert pacer.reserve(500) == pytest.approx(0.5)
    clock.now += 0.5
    assert pacer.reserve(1000) == pytest.approx(1.0)
    clock.now += 1.0
    assert pacer.reserve(0) == 0

    clock.now += 60
    assert pacer.reserve(1500) == pytest.approx(0.5), 'an idle period saves up at most one second'


def test_throttle_switches_limit_when_a_game_starts(monkeypatch, tmp_path):
    playing = []
    monkeypatch.setattr(throttle, 'games_running', lambda folder: bool(playing))
    clock = Clock()
    pacer = Throttle(SpeedLimits(max_speed_while_playing=1000, running_games_dir=str(tmp_path)), clock=clock)

    assert pacer.reserve(10_000) == 0 and pacer.rate == 0
    playing.append(True)
    clock.now += 1
    assert pacer.reserve(10_000) == 0, 'running games are checked every few seconds, not per chunk'
    clock.now += 1
    assert pacer.reserve(1500) == pytest.approx(0.5), 'the new limit applies, with one second of burst'
    assert (pacer.rate, pacer.playing) == (1000, True)


def test_games_running_sees_locks_held_by_other_processes(tmp_path):
    assert not games_running(tmp_path)
    (tmp_path / 'stale-1.lock').write_text('')
    assert not games_running(tmp_path), 'a lock file nobody holds is a leftover'

    holder = subprocess.Popen([sys.executable, '-c', HOLD_LOCK, str(tmp_path / 'game-2.lock')],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == 'held'
        assert games_running(tmp_path)
    finally:
        holder.stdin.close()
        holder.wait(timeout=30)
    assert not games_running(tmp_path), 'the lock goes away with its process'


def test_launch_holds_the_running_lock_while_the_game_runs(fake_game, tmp_path, monkeypatch):
    install = json.loads((fake_game / 'installed.json').read_text())
    game_dir = tmp_path / 'FishGame'
    if sys.platform == 'win32':
        (game_dir / 'slow.cmd').write_text('@ping -n 5 127.0.0.1 >nul\r\n')
        install['Fish']['executable'] = 'slow.cmd'
    else:
        (game_dir / 'slow.sh').write_text('#!/bin/sh\nsleep 4\n')
        (game_dir / 'slow.sh').chmod(0o755)
        install['Fish']['executable'] = 'slow.sh'
    (fake_game / 'installed.json').write_text(json.dumps(install))
    running_dir = fake_game / 'running'

    launch = subprocess.Popen([sys.executable, '-m', 'heirloom.cli', 'launch', 'Fish', '--offline'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen_running = False
    deadline = time.monotonic() + 30
    while launch.poll() is None and time.monotonic() < deadline:
        if running_dir.is_dir() and games_running(running_dir):
            seen_running = True
            break
        time.sleep(0.05)
    assert launch.wait(timeout=30) == 0
    assert seen_running
    assert not games_running(running_dir)
    assert list(running_dir.iterdir()) == [], 'launch removes its lock file'
