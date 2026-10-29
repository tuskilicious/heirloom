"""The backend of "heirloom gui": the library it shows, the jobs it runs, and theme CSS. No window needed."""
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import pytest

from heirloom.gui.app import GuiApi, Job, Jobs, read_library
from heirloom.lfs.lgndry import LGDLFS
from heirloom.models.game import GameAsset, PlaytimeSession
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
        {'type': 'DieselGameBoxTall', 'url': 'https://cdn/fish-tall.jpg'},
        {'type': 'DieselGameBox', 'url': 'https://cdn/fish-wide.jpg'}])
    write_meta(fake_game, 'Goo', 'World of Goo', customAttributes={'CloudSaveFolder': {'value': '{AppData}/Goo'}})
    write_meta(fake_game, 'FishDLC', 'Fish Game Soundtrack', mainGameItem={'id': 'fish'})
    lgd = LGDLFS()
    lgd.assets = {'Linux': [GameAsset(app_name='Fish', build_version='2')],
                  'Windows': [GameAsset(app_name='Goo', build_version='7')]}
    day = datetime(2026, 10, 26, 20, tzinfo=timezone.utc)
    lgd.add_playtime_session('Fish', PlaytimeSession(day, day + timedelta(hours=2), 0))
    lgd.add_playtime_session('Fish', PlaytimeSession(day - timedelta(days=3), day - timedelta(days=3, minutes=-30)))

    fish, goo = read_library(LGDLFS())
    assert fish == {'app_name': 'Fish', 'title': 'Fish Game', 'cover': 'https://cdn/fish-tall.jpg',
                    'art': 'https://cdn/fish-wide.jpg', 'installed': True, 'version': '1', 'update': True,
                    'size': 1024 ** 3, 'store': None, 'cloud_saves': False, 'played': 2.5 * 3600, 'last_played': '2026-10-26T22:00:00+00:00'}
    assert goo == {'app_name': 'Goo', 'title': 'World of Goo', 'cover': '', 'art': '', 'installed': False,
                   'version': '7', 'update': False, 'size': None, 'store': None, 'cloud_saves': True, 'played': 0,
                   'last_played': None}, 'not installed, and DLC is left out'


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
                              'message': 'Preparing download for "Fish Game" (Fish)...', 'options': []}
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
    assert logged_out._command(Job(4, 'repair', 'Fish', 'Fish Game'))[-3:] == ['-y', 'repair', 'Fish']
    assert logged_out._command(Job(5, 'sync', 'Fish', 'Fish Game'))[-3:] == ['-y', 'sync-saves', 'Fish']

    (fake_game / 'user.json').write_text(json.dumps({'account_id': 'abc', 'displayName': 'Tester',
                                                     'access_token': 'a', 'refresh_token': 'r'}))
    logged_in = api()
    assert logged_in.state()['user'] == 'Tester'
    assert logged_in._command(play)[-3:] == ['-y', 'launch', 'Fish']


def test_updates_start_by_themselves(fake_game, monkeypatch):
    LGDLFS().assets = {'Linux': [GameAsset(app_name='Fish', build_version='2')]}

    def api_starting(started):
        api = GuiApi(None, lambda: {})
        monkeypatch.setattr(api._jobs, 'add', lambda kind, app_name, title: started.append((kind, app_name)))
        return api

    started = []
    api = api_starting(started)
    assert api._update_games() == 'Updating by itself: Fish Game.' and started == [('install', 'Fish')]
    for status, kind in (('running', 'play'), ('stopped', 'install'), ('failed', 'install')):
        started.clear()
        api._jobs._jobs[:] = [Job(1, kind, 'Fish', 'Fish Game', status)]
        assert api._update_games() == '' and not started, f'{kind} {status}: left alone'

    (fake_game / 'config.ini').write_text('[Heirloom]\ndisable_auto_updates = true\n')
    started.clear()
    assert api_starting(started)._update_games() == '' and not started, 'turned off'


@pytest.mark.skipif(sys.platform != 'win32', reason='the window offers the overlay on Windows only')
def test_epic_overlay(lgd_home, tmp_path, monkeypatch):
    registry = {'overlay_path': None}
    monkeypatch.setattr('heirloom.gui.app.query_registry_entries', lambda: dict(registry))
    monkeypatch.setattr('heirloom.gui.app.remove_registry_entries', lambda: registry.update(overlay_path=None))
    monkeypatch.setattr('heirloom.gui.app.add_registry_entries', lambda path: registry.update(overlay_path=path))
    api = GuiApi(None, lambda: {}, command=lambda: ['heirloom'])
    assert api.overlay() == {'installed': False, 'version': '', 'enabled': False}
    with pytest.raises(ValueError):
        api.set_overlay(True)
    assert api._command(Job(1, 'overlay', '', 'Epic overlay')) == ['heirloom', '-y', 'eos-overlay', 'install']

    overlay_dir = tmp_path / 'Overlay'
    overlay_dir.mkdir()
    (overlay_dir / 'EOSOVH-Win64-Shipping.dll').touch()
    lgd_home.mkdir(exist_ok=True)
    (lgd_home / 'overlay_install.json').write_text(json.dumps(
        {'app_name': '98bc04bc842e4906993fd6d6644ffb8d', 'title': 'Epic overlay', 'version': '1.3.5',
         'install_path': str(overlay_dir)}))
    assert api.set_overlay(True) == {'installed': True, 'version': '1.3.5', 'enabled': True}
    assert registry['overlay_path'] == str(overlay_dir)
    assert api.set_overlay(False)['enabled'] is False and registry['overlay_path'] is None


def test_installing_with_a_folder_and_dlc(fake_game, tmp_path):
    info = {'game': {'owned_dlc': [{'title': 'Fish Soundtrack', 'installable': True},
                                   {'title': 'Fish Hat', 'installable': None}]},
            'manifest': {'download_size': 3 * 1024 ** 3, 'disk_size': 5 * 1024 ** 3}}
    # stands in for "heirloom info <game> --json": logs, then the JSON
    script = f'import sys; print("[cli] INFO: Getting game metadata..."); print({json.dumps(json.dumps(info))})'
    api = GuiApi(None, lambda: {}, command=lambda: [sys.executable, '-c', script])
    found = api.install_info('Fish')
    assert (found['download_size'], found['disk_size'], found['dlcs']) == (3 * 1024 ** 3, 5 * 1024 ** 3,
                                                                           ['Fish Soundtrack'])
    assert found['free'] > 0, 'the install folder need not exist yet: its drive is asked'

    install = Job(1, 'install', 'Fish', 'Fish Game', options=['--base-path', str(tmp_path), '--skip-dlcs'])
    assert api._command(install)[-5:] == ['install', 'Fish', '--base-path', str(tmp_path), '--skip-dlcs']
    with pytest.raises(ValueError):
        api.install('Fish', folder='games')


def test_settings_read_and_write_the_config(lgd_home, tmp_path):
    lgd_home.mkdir()
    (lgd_home / 'config.ini').write_text('[Heirloom]\nmax_download_speed = 500K\ndisable_cloud_save_sync = true\n')
    api = GuiApi(None, lambda: {})
    settings = api.settings()
    assert settings['max_download_speed'] == 0.49 and settings['max_download_speed_while_playing'] == 0
    assert settings['cloud_saves'] is False and settings['auto_updates'] is True

    games = tmp_path / 'My Games'
    api.set_setting('install_dir', str(games))
    api.set_setting('max_download_speed_while_playing', '2.5')
    settings = api.set_setting('cloud_saves', True)
    assert (settings['install_dir'], settings['max_download_speed_while_playing'], settings['cloud_saves']) == \
        (str(games), 2.5, True)
    config = (lgd_home / 'config.ini').read_text()
    assert 'disable_cloud_save_sync = false' in config and 'max_download_speed_while_playing = 2.5' in config

    for name, value in (('max_download_speed', 'fast'), ('install_dir', 'relative/games'), ('theme', 'neon'),
                        ('auto_updates', 'yes')):
        with pytest.raises(ValueError):
            api.set_setting(name, value)
    assert api.settings()['max_download_speed'] == 0.49, 'a refused value changes nothing'


def test_the_window_opens_as_it_was_left(lgd_home):
    api = GuiApi(None, lambda: {})
    assert api.view() == {'filter': 'all', 'sort': 'title', 'rail_collapsed': False}
    api.set_view({'filter': 'installed', 'sort': 'recent', 'rail_collapsed': True})
    api.set_view({'sort': 'nonsense', 'filter': None, 'colour': 'red'})
    assert GuiApi(None, lambda: {}).view() == {'filter': 'installed', 'sort': 'recent', 'rail_collapsed': True}, \
        'kept between runs, and anything unknown left out'
    (lgd_home / 'window.json').write_text('not json')
    assert api.view()['sort'] == 'title'


def test_open_folder_of_a_game_whose_files_are_gone(fake_game, tmp_path):
    for child in (tmp_path / 'FishGame').iterdir():
        child.unlink()
    (tmp_path / 'FishGame').rmdir()
    api = GuiApi(None, lambda: {})
    api.open_folder('Fish')
    assert api.state()['notice'] == 'The folder of Fish Game is gone. Repair it, or uninstall it.'


@pytest.mark.skipif(sys.platform != 'win32', reason='desktop shortcuts are made on Windows')
def test_desktop_shortcut_plays_the_game_with_its_icon(fake_game, tmp_path, monkeypatch):
    ran = []
    monkeypatch.setattr('heirloom.gui.app.subprocess.run', lambda command, env, **options: ran.append(env))
    write_meta(fake_game, 'Fish', 'Fish: The Game?')
    api = GuiApi('my config.ini', lambda: {}, command=lambda: ['C:\\Heirloom\\heirloom.exe'])
    api.create_shortcut('Fish')
    env, = ran
    assert env['HL_NAME'] == 'Fish The Game', 'without the characters Windows does not allow in file names'
    assert env['HL_TARGET'] == 'C:\\Heirloom\\heirloom.exe'
    assert env['HL_ARGUMENTS'] == '-c "my config.ini" -y launch Fish'
    assert env['HL_ICON'] == str(tmp_path / 'FishGame' / 'fish.cmd')
    assert api.state()['notice'] == 'Added "Fish The Game" to your desktop.'


def test_theme_css_for_the_window(lgd_home, tmp_path):
    themes_dir = tmp_path / 'themes'
    themes_dir.mkdir()
    (themes_dir / 'neon.json').write_text(json.dumps({'name': 'neon', 'gui_css': 'neon.css'}))
    (themes_dir / 'neon.css').write_text(':root { --accent: #00f0ff; }')
    (themes_dir / 'sneaky.json').write_text(json.dumps({'name': 'sneaky', 'gui_css': '../secret.css'}))
    themes, errors = load_themes(themes_dir, [])
    assert themes['neon'].css == ':root { --accent: #00f0ff; }'
    assert 'sneaky' not in themes and 'next to the theme' in errors['sneaky.json (user)']

    window_dir = lgd_home / 'themes'
    window_dir.mkdir(parents=True)
    (window_dir / 'copy-of-neon.css').write_text(':root { --accent: #00f0ff; }')
    (window_dir / 'paper_white.css').write_text(':root { --bg: #fff; }')

    api = GuiApi(None, lambda: themes)
    assert api.themes() == {'active': 'heirloom', 'css': '', 'themes': [
        {'name': 'heirloom', 'title': 'Heirloom'}, {'name': 'fluent', 'title': 'Fluent'},
        {'name': 'impeccable', 'title': 'Impeccable'}, {'name': 'neon', 'title': 'neon'},
        {'name': 'paper_white', 'title': 'Paper white'}]}, \
        "its own look and the ones that come with it, then themes with CSS and CSS files, " \
        "not terminal themes or the same CSS twice"
    assert 'Chakra Petch' in api.use_theme('impeccable')['css']
    switched = api.use_theme('paper_white')
    assert (switched['active'], switched['css']) == ('paper_white', ':root { --bg: #fff; }')
    config = (lgd_home / 'config.ini').read_text()
    assert 'window_theme = paper_white' in config and '\ntheme =' not in config, 'the terminal keeps its theme'
    with pytest.raises(ValueError):
        api.use_theme('default')
