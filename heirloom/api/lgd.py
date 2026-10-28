# !/usr/bin/env python

import logging
from platform import system

import requests

from heirloom import __version__

RELEASES = 'https://api.github.com/repos/tuskilicious/heirloom/releases/latest'
# the release file to download on each platform, first one found
DOWNLOADS = {
    'windows': ('heirloom_windows_x64_setup.exe', 'heirloom_windows_x64.exe'),
    'macos': ('heirloom_macOS.zip',),
    'linux': ('heirloom_linux_x64',),
}


def release_info(release: dict) -> dict:
    """A GitHub release of Heirloom, in the shape of the release_info of Legendary's version feed"""
    # releases are titled like 0.25.0 "Strongbox", and their notes start with a one-paragraph summary
    name = release.get('name') or release['tag_name']
    assets = {asset['name']: asset['browser_download_url'] for asset in release.get('assets', [])}
    return {
        'version': release['tag_name'],
        'name': name.split('"')[1] if name.count('"') == 2 else name,
        'summary': (release.get('body') or '').strip().split('\n\n')[0],
        'gh_url': release['html_url'],
        'critical': False,
        'downloads': {platform: url for platform, names in DOWNLOADS.items()
                      if (url := next((assets[n] for n in names if n in assets), None))},
    }


def is_newer(version: str, than: str) -> bool:
    try:
        return tuple(map(int, version.split('.'))) > tuple(map(int, than.split('.')))
    except ValueError:
        return False


class LGDAPI:
    _user_agent = f'Heirloom/{__version__} ({system()})'
    _api_host = 'api.legendary.gl'

    def __init__(self):
        self.session = requests.session()
        self.log = logging.getLogger('LGDAPI')
        self.session.headers['User-Agent'] = self._user_agent

    def get_version_information(self):
        r = self.session.get(f'https://{self._api_host}/v1/version.json',
                             timeout=10.0)
        r.raise_for_status()
        return r.json()

    def get_heirloom_release(self) -> dict:
        r = self.session.get(RELEASES, timeout=10.0)
        r.raise_for_status()
        return release_info(r.json())

    def get_sdl_config(self, app_name):
        r = self.session.get(f'https://{self._api_host}/v1/sdl/{app_name}.json',
                             timeout=10.0)
        r.raise_for_status()
        return r.json()
