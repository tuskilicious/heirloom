"""Heirloom's own update notice, from its latest GitHub release."""
import pytest
import requests

from heirloom import __version__
from heirloom.api.lgd import LGDAPI, is_newer, release_info
from heirloom.core import HeirloomCore
from heirloom.gui.app import GuiApi

GITHUB_RELEASE = {
    'tag_name': '9.1.0',
    'name': '9.1.0 "Heirloom Tomato"',
    'html_url': 'https://github.com/tuskilicious/heirloom/releases/tag/9.1.0',
    'body': 'Heirloom learns to grow tomatoes.\n\n### New\n- **Tomatoes.** Red ones.',
    'assets': [{'name': name, 'browser_download_url': f'https://github.com/dl/{name}'} for name in (
        'heirloom_windows_x64.exe', 'heirloom_windows_x64_setup.exe', 'heirloom_macOS.zip', 'heirloom_linux_arm64')],
}


def test_release_reads_like_the_feeds_release_info():
    assert release_info(GITHUB_RELEASE) == {
        'version': '9.1.0',
        'name': 'Heirloom Tomato',
        'summary': 'Heirloom learns to grow tomatoes.',
        'gh_url': 'https://github.com/tuskilicious/heirloom/releases/tag/9.1.0',
        'critical': False,
        'downloads': {'windows': 'https://github.com/dl/heirloom_windows_x64_setup.exe',
                      'macos': 'https://github.com/dl/heirloom_macOS.zip'},
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
    assert later.update_available, 'read from the cache for a day'


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
    assert core.lgd.get_cached_version()['data'] == {'legendary_config': {}}


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
