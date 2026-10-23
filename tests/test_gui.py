"""The backend of "heirloom gui": the library it shows, the jobs it runs, and theme CSS. No window needed."""
import json
import sys
import time

import pytest

from heirloom.gui.app import GuiApi, Job, Jobs, read_library
from heirloom.lfs.lgndry import LGDLFS
from heirloom.models.game import GameAsset
from heirloom.themes import load_themes

# Stands in for "heirloom install": prints download log lines like heirloom's, then exits with the given code,
# or stops on Ctrl-C (Ctrl+Break on Windows) like heirloom does.
JOB = '''
import sys, time
from heirloom.downloader.queue import handle_ctrl_break_as_ctrl_c

handle_ctrl_break_as_ctrl_c()
kind = sys.argv[1]
print('[cli] INFO: Preparing download for "Fish Game" (Fish)...', flush=True)
print('[DLManager] INFO: = Progress: 42.50% (17/40), Running for 00:00:03, ETA: 00:00:04', flush=True)
print('[DLManager] INFO:  + Download\\t- 12.34 MiB/s (raw) / 20.00 MiB/s (decompressed)', flush=True)
if kind == 'fail':
    print('[cli] ERROR: Not enough free disk space', flush=True)
    sys.exit(1)
if kind == 'slow':
    try:
        for _ in range(300):
            time.sleep(0.1)
    except KeyboardInterrupt:
        print('[cli] INFO: Command was aborted via KeyboardInterrupt, cleaning up...', flush=True)
        sys.exit(0)
'''


def write_meta(lgd_home, app_name, title, **metadata):
    (lgd_home / 'metadata' / f'{app_name}.json').write_text(json.dumps({
        'app_name': app_name, 'app_title': title, 'metadata': metadata, 'asset_infos': {}}))


def test_library_from_cached_files(fake_game):
    write_meta(fake_game, 'Fish', 'Fish Game', keyImages=[
        {'type': 'Thumbnail', 'url': 'https://cdn/fish-thumb.jpg'},
        {'type': 'DieselGameBoxTall', 'url': 'https://cdn/fish-tall.jpg'}])
    write_meta(fake_game, 'Goo', 'World of Goo')
    write_meta(fake_game, 'FishDLC', 'Fish Game Soundtrack', mainGameItem={'id': 'fish'})
    LGDLFS().assets = {'Linux': [GameAsset(app_name='Fish', build_version='2')],
                       'Windows': [GameAsset(app_name='Goo', build_version='7')]}

    fish, goo = read_library(LGDLFS())
    assert fish == {'app_name': 'Fish', 'title': 'Fish Game', 'cover': 'https://cdn/fish-tall.jpg', 'installed': True,
                    'version': '1', 'update': True, 'size': 1024 ** 3, 'store': None}
    assert goo == {'app_name': 'Goo', 'title': 'World of Goo', 'cover': '', 'installed': False, 'version': '7',
                   'update': False, 'size': None, 'store': None}, 'not installed, and DLC is left out'


def run_jobs(jobs, kinds, until_done=True):
    for kind in kinds:
        jobs.add('install', kind, kind)
    deadline = time.monotonic() + 30
    while until_done and any(job['status'] in ('queued', 'running') for job in jobs.snapshot()):
        assert time.monotonic() < deadline, jobs.snapshot()
        time.sleep(0.05)
    return jobs.snapshot()


def fake_jobs(started=None):
    def command(job):
        if started is not None:
            started.append(job.app_name)
        return [sys.executable, '-c', JOB, job.app_name]
    finished = []
    return Jobs(command, finished.append), finished


def test_downloads_run_one_at_a_time_and_report_progress():
    started = []
    jobs, finished = fake_jobs(started)
    ok, failing = run_jobs(jobs, ['ok', 'fail'])
    assert started == ['ok', 'fail']
    assert ok | {'id': 0} == {'id': 0, 'kind': 'install', 'app_name': 'ok', 'title': 'ok', 'status': 'done',
                              'progress': 42.5, 'speed': '12.34 MiB/s',
                              'message': 'Preparing download for "Fish Game" (Fish)...'}
    assert failing['status'] == 'failed' and failing['message'] == 'Not enough free disk space'
    assert [job.app_name for job in finished] == ['ok', 'fail']


def test_a_second_download_waits_and_stop_ends_the_first_cleanly():
    jobs, _ = fake_jobs()
    slow, waiting = run_jobs(jobs, ['slow', 'ok'], until_done=False)
    assert (slow['status'], waiting['status']) == ('running', 'queued')

    deadline = time.monotonic() + 10
    while jobs.snapshot()[0]['progress'] is None:
        assert time.monotonic() < deadline
        time.sleep(0.05)
    jobs.stop(slow['id'])
    slow, waiting = run_jobs(jobs, [])
    assert slow['status'] == 'stopped' and 'aborted' in slow['message'], 'stopped like Ctrl-C, not killed'
    assert waiting['status'] == 'done', 'the next download starts after the stop'


def test_commands_for_each_action(fake_game):
    def api():
        return GuiApi('custom.ini', lambda: {}, command=lambda: ['heirloom'])

    play = Job(2, 'play', 'Fish', 'Fish Game')
    logged_out = api()
    assert logged_out.state()['user'] is None, 'an account name without a login is not logged in'
    assert logged_out._command(play)[-4:] == ['-y', 'launch', 'Fish', '--offline'], 'only offline works without one'
    assert logged_out._command(Job(1, 'install', 'Fish', 'Fish Game')) == ['heirloom', '-c', 'custom.ini', '-y',
                                                                            'install', 'Fish']
    assert logged_out._command(Job(3, 'login', '', 'Epic Games account'))[-1] == 'auth'

    (fake_game / 'user.json').write_text(json.dumps({'account_id': 'abc', 'displayName': 'Tester',
                                                     'access_token': 'a', 'refresh_token': 'r'}))
    logged_in = api()
    assert logged_in.state()['user'] == 'Tester'
    assert logged_in._command(play)[-3:] == ['-y', 'launch', 'Fish']


def test_theme_css_for_the_window(lgd_home, tmp_path):
    themes_dir = tmp_path / 'themes'
    themes_dir.mkdir()
    (themes_dir / 'neon.json').write_text(json.dumps({'name': 'neon', 'gui_css': 'neon.css'}))
    (themes_dir / 'neon.css').write_text(':root { --accent: #00f0ff; }')
    (themes_dir / 'sneaky.json').write_text(json.dumps({'name': 'sneaky', 'gui_css': '../secret.css'}))
    themes, errors = load_themes(themes_dir, [])
    assert themes['neon'].css == ':root { --accent: #00f0ff; }'
    assert 'sneaky' not in themes and 'next to the theme' in errors['sneaky.json (user)']

    api = GuiApi(None, lambda: themes)
    assert api.themes()['active'] == 'default' and api.themes()['css'] == ''
    switched = api.use_theme('neon')
    assert (switched['active'], switched['css']) == ('neon', ':root { --accent: #00f0ff; }')
    assert 'theme = neon' in (lgd_home / 'config.ini').read_text(), 'the terminal uses the same theme'
    with pytest.raises(ValueError):
        api.use_theme('nope')
