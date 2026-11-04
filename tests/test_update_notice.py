"""Heirloom's own update notice, from its latest GitHub release."""
import hashlib
import time

import pytest
import requests

from heirloom import __version__, desktop
from heirloom.api.lgd import LGDAPI, is_newer, release_info
from heirloom.core import HeirloomCore
from heirloom.gui.app import GuiApi, Job
from heirloom.gui.self_update import DOWNLOAD_PREFIX, fetch_setup
from heirloom.lfs.lgndry import LGDLFS

GITHUB_RELEASE = {
    'tag_name': '9.1.0',
    'name': '9.1.0 "Heirloom Tomato"',
    'html_url': 'https://github.com/tuskilicious/heirloom/releases/tag/9.1.0',
    'body': 'Heirloom learns to grow tomatoes.\n\n### New\n- **Tomatoes.** Red ones.',
    'assets': [{'name': name, 'browser_download_url': f'https://github.com/dl/{name}'} for name in (
        'heirloom_windows_x64.exe', 'heirloom_windows_x64_setup.exe', 'heirloom_linux_arm64')],
}


def test_release_reads_like_the_feeds_release_info(monkeypatch):
    monkeypatch.setattr('heirloom.api.lgd.UPDATE_FILE', 'heirloom_windows_x64_setup.exe')
    assert release_info(GITHUB_RELEASE) == {
        'version': '9.1.0',
        'name': 'Heirloom Tomato',
        'summary': 'Heirloom learns to grow tomatoes.',
        'gh_url': 'https://github.com/tuskilicious/heirloom/releases/tag/9.1.0',
        'critical': False,
        'setup': {'url': 'https://github.com/dl/heirloom_windows_x64_setup.exe', 'sha256': ''},
        'downloads': {'windows': 'https://github.com/dl/heirloom_windows_x64_setup.exe'},
    }, 'the installer is preferred, and a platform without its file has no download'


@pytest.mark.parametrize(('version', 'than', 'newer'), [
    ('0.26.0', '0.25.0', True), ('0.25.1', '0.25.0', True), ('1.0.0', '0.99.9', True), ('0.25.10', '0.25.9', True),
    ('0.25.0', '0.25.0', False), ('0.24.9', '0.25.0', False), ('0.26.0-beta', '0.25.0', False),
])
def test_version_comparison(version, than, newer):
    assert is_newer(version, than) is newer


@pytest.fixture
def core(lgd_home, monkeypatch):
    monkeypatch.setattr(LGDAPI, 'get_version_information', lambda self: {'legendary_config': {}})
    return HeirloomCore()


def test_newer_release_is_an_update(core, monkeypatch):
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release', lambda self: release_info(GITHUB_RELEASE))
    core.check_for_updates(force=True)
    assert core.update_available
    assert core.get_update_info()['version'] == '9.1.0'

    def fetch(self):
        raise AssertionError('fetched again')
    monkeypatch.setattr(LGDAPI, 'get_version_information', fetch)
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release', fetch)
    later = HeirloomCore()
    later.check_for_updates()
    assert later.update_available, 'read from the cache within the hour'

    # an hour on, GitHub is asked again for a newer Heirloom, but the feed is kept for its day
    cached = later.lgd.get_cached_version()
    cached['data']['heirloom_release_checked'] -= 2 * 3600
    fetched = cached['last_update']
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release',
                        lambda self: release_info(GITHUB_RELEASE | {'tag_name': '9.2.0'}))
    later.check_for_updates()
    assert later.get_update_info()['version'] == '9.2.0'
    assert later.lgd.get_cached_version()['last_update'] == fetched, 'the feed was not fetched again'


def test_a_refresh_of_the_window_asks_github_within_the_hour(core, monkeypatch):
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release', lambda self: release_info(GITHUB_RELEASE))
    core.check_for_updates(force=True)
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release',
                        lambda self: release_info(GITHUB_RELEASE | {'tag_name': '9.2.0'}))

    def login(self):
        self.check_for_updates()
        return True

    monkeypatch.setattr('heirloom.gui.app.logged_in_user', lambda lgd: 'Tester')
    monkeypatch.setattr(HeirloomCore, 'login', login)
    monkeypatch.setattr(HeirloomCore, 'get_game_and_dlc_list', lambda self, **kwargs: None)
    monkeypatch.setattr(HeirloomCore, 'update_notice_enabled', lambda self: True)
    monkeypatch.setattr('heirloom.gui.app.free_games', lambda *_: [])
    api = GuiApi(None, lambda: {})
    api._refresh()
    assert api.state()['update']['version'] == '9.2.0'


def test_current_release_is_no_update(core, monkeypatch):
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release',
                        lambda self: release_info(GITHUB_RELEASE | {'tag_name': __version__}))
    core.check_for_updates(force=True)
    assert not core.update_available


def test_unreachable_github_is_no_update_and_keeps_the_feed(core, monkeypatch):
    def offline(self):
        raise requests.ConnectionError('no GitHub today')
    monkeypatch.setattr(LGDAPI, 'get_heirloom_release', offline)
    core.check_for_updates(force=True)
    assert not core.update_available
    assert 'heirloom_release' not in core.lgd.get_cached_version()['data']
    assert core.lgd.get_cached_version()['data']['legendary_config'] == {}


def test_window_offers_the_update(lgd_home, monkeypatch):
    monkeypatch.setattr('heirloom.gui.app.logged_in_user', lambda lgd: 'Tester')
    monkeypatch.setattr(HeirloomCore, 'login', lambda self: setattr(self, 'update_available', True) or True)
    monkeypatch.setattr(HeirloomCore, 'get_game_and_dlc_list', lambda self, **kwargs: None)
    monkeypatch.setattr(HeirloomCore, 'update_notice_enabled', lambda self: True)
    monkeypatch.setattr(HeirloomCore, 'get_update_info', lambda self: release_info(GITHUB_RELEASE))
    api = GuiApi(None, lambda: {})
    assert api.state()['update'] is None

    api._refresh()
    assert api.state()['update'] == {'version': '9.1.0', 'name': 'Heirloom Tomato',
                                     'url': 'https://github.com/tuskilicious/heirloom/releases/tag/9.1.0'}

    monkeypatch.setattr(HeirloomCore, 'update_notice_enabled', lambda self: False)
    api._refresh()
    assert api.state()['update'] is None, 'disable_update_notice hides it in the window too'


@pytest.fixture
def setup_files(lgd_home, monkeypatch):
    """A window that came from the installer, and a release whose installer holds these bytes"""
    monkeypatch.setattr(desktop, 'can_update_itself', lambda: True)
    monkeypatch.setattr(desktop, 'other_heirlooms_running', lambda: False)

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, _):
            return [b'installer']

    monkeypatch.setattr('heirloom.gui.self_update.requests.get', lambda *_, **__: Response())
    return {'version': '9.1.0', 'setup': {'url': f'{DOWNLOAD_PREFIX}9.1.0/setup.exe',
                                          'sha256': hashlib.sha256(b'installer').hexdigest()}}


def fetched_api(release):
    api = GuiApi(None, lambda: {})
    assert api._self_update(release) == ''
    for _ in range(100):
        if not api._fetching_setup:
            break
        time.sleep(0.02)
    return api


def test_a_new_release_waits_ready_and_installs_once(setup_files, monkeypatch):
    started = []
    monkeypatch.setattr(desktop, 'start_install', started.append)
    api = fetched_api(setup_files)
    assert api.state()['update_ready'] and api._setup.read_bytes() == b'installer'

    api._jobs._jobs[:] = [Job(1, 'play', 'Fish', 'Fish Game', 'running')]
    assert not api._install_update() and not started, 'not while a game is running'
    api._jobs._jobs[:] = [Job(1, 'play', 'Fish', 'Fish Game', 'done')]
    monkeypatch.setattr(desktop, 'other_heirlooms_running', lambda: True)
    assert not api._install_update() and not started, 'nor while a shortcut or a terminal is using its files'
    monkeypatch.setattr(desktop, 'other_heirlooms_running', lambda: False)

    setup = api._setup
    assert api._install_update() and started == [setup]

    # it reopened on the old version, so the install failed
    assert 'could not install itself' in GuiApi(None, lambda: {})._self_update(setup_files), 'one try for each release'
    assert not fetched_api(None).state()['update_ready'] and not setup.parent.exists(), 'up to date: cleared up'


def test_an_installer_that_does_not_match_is_not_kept(setup_files):
    setup_files['setup']['sha256'] = '0' * 64
    api = fetched_api(setup_files)
    assert not api.state()['update_ready']
    assert not list((LGDLFS().path / 'self_update').iterdir()), 'neither it nor its partial download stays'


@pytest.mark.parametrize('setup', [{'url': 'https://example.com/setup.exe', 'sha256': 'abc'},
                                   {'url': f'{DOWNLOAD_PREFIX}9.1.0/setup.exe', 'sha256': ''}])
def test_an_installer_from_elsewhere_or_without_a_checksum_is_refused(setup_files, setup, tmp_path):
    with pytest.raises(ValueError):
        fetch_setup(setup, tmp_path / 'update' / 'setup.exe')
    assert not (tmp_path / 'update').exists()


def test_turned_off_or_outside_the_installer_nothing_is_downloaded(setup_files, monkeypatch):
    api = GuiApi(None, lambda: {})
    lgd = api._lgd()
    lgd.config.set('Heirloom', 'disable_self_update', 'true')
    lgd.save_config()
    assert api._self_update(setup_files) == '' and not api._fetching_setup
    lgd.config.set('Heirloom', 'disable_self_update', 'false')
    lgd.save_config()
    monkeypatch.setattr(desktop, 'can_update_itself', lambda: False)
    assert api._self_update(setup_files) == '' and not api._fetching_setup
