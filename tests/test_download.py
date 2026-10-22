import logging
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import QueueListener
from multiprocessing import Queue

import pytest

from heirloom.downloader.mp.manager import DLManager
from heirloom.downloader.throttle import SpeedLimits
from heirloom.models.manifest import Manifest
from heirloom.utils.savegame_helper import SaveGameHelper

from .test_formats import _make_save
from .test_throttle import HOLD_LOCK


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def cdn(tmp_path):
    """Packs a fake game into chunks + manifest and serves the chunks over HTTP."""
    files = _make_save(tmp_path / 'src')
    out = SaveGameHelper().package_savegame(str(tmp_path / 'src'))
    blob = out.pop(next(name for name in out if name.startswith('manifests/')))
    blob.seek(0)
    manifest = Manifest.read_all(blob.read())

    root = tmp_path / 'cdn'
    for rel, fobj in out.items():
        fobj.seek(0)
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(fobj.read())

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}', manifest, files
    server.shutdown()


def _install(base_url, manifest, dest, resume_file, speed_limits=None, **analysis_kwargs):
    log_q = Queue(-1)
    records = []
    listener = QueueListener(log_q, logging.Handler())
    listener.handlers[0].emit = records.append
    listener.start()
    try:
        dlm = DLManager(str(dest), base_url, {}, resume_file=str(resume_file), max_workers=2,
                        max_shared_memory=64 * 1024 * 1024, speed_limits=speed_limits)
        analysis = dlm.run_analysis(manifest=manifest, **analysis_kwargs)
        dlm.logging_queue = log_q
        dlm.start()
        dlm.join(timeout=120)
        assert dlm.exitcode == 0
    finally:
        listener.stop()
    return analysis, [r.getMessage() for r in records]


def test_download_manager_installs_and_resumes(cdn, tmp_path):
    base_url, manifest, files = cdn
    dest = tmp_path / 'game'
    resume = tmp_path / 'game.resume'

    _, log = _install(base_url, manifest, dest, resume)
    for name, data in files.items():
        assert (dest / name).read_bytes() == data, name
    assert not resume.exists(), 'resume file removed after a clean install'
    assert not any('failed' in msg.lower() for msg in log), log

    resume.write_text(''.join(f'{fm.sha_hash.hex()}:{fm.filename}\n'
                              for fm in manifest.file_manifest_list.elements), encoding='utf-8')
    (dest / 'settings.ini').unlink()
    analysis, _ = _install(base_url, manifest, dest, resume)
    assert analysis.dl_size > 0, 'file missing on disk is redownloaded despite resume entry'
    assert (dest / 'settings.ini').read_bytes() == files['settings.ini']


def test_download_manager_fills_in_missing_files_without_resume_file(cdn, tmp_path):
    base_url, manifest, files = cdn
    dest = tmp_path / 'game'
    _install(base_url, manifest, dest, tmp_path / 'r1')

    (dest / 'slots' / 'two.sav').unlink()
    analysis, _ = _install(base_url, manifest, dest, tmp_path / 'r2', old_manifest=manifest)
    assert analysis.install_size > 0
    assert (dest / 'slots' / 'two.sav').read_bytes() == files['slots/two.sav']


def _timed_install(cdn, dest, speed_limits=None):
    base_url, manifest, files = cdn
    start = time.monotonic()
    _, log = _install(base_url, manifest, dest, dest.with_suffix('.resume'), speed_limits=speed_limits)
    elapsed = time.monotonic() - start
    for name, data in files.items():
        assert (dest / name).read_bytes() == data, name
    return elapsed, log


THROTTLED_SECONDS = 8


def _throttled_rate(manifest):
    """
    A limit at which the last chunk cannot start before THROTTLED_SECONDS, however fast the machine.
    How long an unthrottled download takes depends on process start-up and is only compared loosely.
    """
    return sum(chunk.file_size for chunk in manifest.chunk_data_list.elements) // THROTTLED_SECONDS


def test_download_speed_limit_slows_the_download(cdn, tmp_path):
    rate = _throttled_rate(cdn[1])
    unlimited, _ = _timed_install(cdn, tmp_path / 'fast')
    limited, log = _timed_install(cdn, tmp_path / 'slow', SpeedLimits(max_speed=rate))
    assert limited >= THROTTLED_SECONDS - 0.5, f'took {limited:.1f}s limited'
    assert unlimited < limited - 2, f'took {unlimited:.1f}s unlimited vs {limited:.1f}s limited'
    assert any('Download speed limit' in msg for msg in log)


def test_lower_limit_applies_while_a_game_is_running(cdn, tmp_path):
    rate = _throttled_rate(cdn[1])
    running = tmp_path / 'running'
    running.mkdir()
    limits = SpeedLimits(max_speed_while_playing=rate, running_games_dir=str(running))

    no_game, _ = _timed_install(cdn, tmp_path / 'idle', limits)
    game = subprocess.Popen([sys.executable, '-c', HOLD_LOCK, str(running / 'Fish-1.lock')],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert game.stdout.readline().strip() == 'held'
        playing, _ = _timed_install(cdn, tmp_path / 'playing', limits)
    finally:
        game.stdin.close()
        game.wait(timeout=30)
    assert playing >= THROTTLED_SECONDS - 0.5, f'took {playing:.1f}s while playing'
    assert no_game < playing - 2, f'took {no_game:.1f}s without a game vs {playing:.1f}s while playing'
