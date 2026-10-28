"""Cloud saves synced around "heirloom launch": a newer cloud save comes down first, a newer local one goes up after."""
import json
import locale
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from heirloom.core import HeirloomCore

# Runs "heirloom launch Fish" with Epic's save service (and the login) replaced: the cloud has a save from an hour
# ago, downloads and uploads are printed instead of done. The fake game can only run offline, so its launch
# parameters are the offline ones, but the launch itself goes the online way.
LAUNCH = '''
import sys
from datetime import datetime, timedelta, timezone
from heirloom.core import HeirloomCore
from heirloom.models.game import SaveGameFile

mode, args = sys.argv[1], sys.argv[2:]
cloud = datetime.now(timezone.utc) - timedelta(hours=1)
manifest = cloud.strftime('%Y.%m.%d-%H.%M.%S.manifest')


def saves(self, app_name=''):
    if mode == 'broken':
        raise ConnectionError('no route to Epic')
    return [SaveGameFile(app_name, f'x/y/{app_name}/z/{manifest}', manifest, cloud.replace(tzinfo=None))]


launch_parameters = HeirloomCore.get_launch_parameters
HeirloomCore.login = lambda self, force_refresh=False: True
HeirloomCore.get_launch_parameters = lambda self, **kw: launch_parameters(self, **(kw | {'offline': True}))
HeirloomCore.get_save_games = saves
HeirloomCore.download_saves = lambda self, app_name='', **kw: print('downloaded', kw['manifest_name'] == manifest)
HeirloomCore.upload_save = lambda self, app_name, save_dir, *rest: print('uploaded', app_name, save_dir)

from heirloom.cli import main
sys.argv = ['heirloom', 'launch', 'Fish', '--skip-version-check', *args]
main()
'''


@pytest.fixture
def cloud_game(fake_game):
    """The fake game with cloud saves in its Saves folder, an old save there, and an executable that saves"""
    installed = json.loads((fake_game / 'installed.json').read_text())
    saves = Path(installed['Fish']['install_path'], 'Saves')
    saves.mkdir()
    old = saves / 'slot1.sav'
    old.write_text('old progress')
    two_hours_ago = time.time() - 2 * 3600
    os.utime(old, (two_hours_ago, two_hours_ago))

    exe = Path(installed['Fish']['install_path'], installed['Fish']['executable'])
    new = saves / 'slot2.sav'
    if sys.platform == 'win32':
        exe.write_text(f'@echo new progress> "{new}"\r\n@exit /b 0\r\n')
    else:
        exe.write_text(f'#!/bin/sh\necho new progress > "{new}"\n')
    set_save_folder(fake_game, '{InstallDir}/Saves')
    return fake_game, saves


def set_save_folder(home, folder):
    (home / 'metadata' / 'Fish.json').write_text(json.dumps({
        'app_name': 'Fish', 'app_title': 'Fish Game', 'asset_infos': {},
        'metadata': {'customAttributes': {'CloudSaveFolder': {'type': 'STRING', 'value': folder}}}}))


def launch(mode, *args):
    result = subprocess.run([sys.executable, '-c', LAUNCH, mode, *args], capture_output=True, timeout=120)
    result.stdout = result.stdout.decode('utf-8')
    result.stderr = result.stderr.decode(locale.getpreferredencoding(False), errors='replace')
    assert result.returncode == 0, result.stderr
    assert 'Fish exited after' in result.stderr, 'the game ran'
    return result


def test_newer_cloud_save_comes_down_before_and_new_save_goes_up_after(cloud_game):
    home, saves = cloud_game
    result = launch('ok')

    assert result.stdout.splitlines() == ['downloaded True', f'uploaded Fish {saves.resolve()}'], result.stderr
    assert (home / 'save-backups' / 'Fish' / 'slot1.sav').read_text() == 'old progress', \
        'the files the download replaces are kept'
    installed = json.loads((home / 'installed.json').read_text())
    assert installed['Fish']['save_path'] == str(saves.resolve()), 'the save folder is remembered'


@pytest.mark.parametrize('off', ['--no-sync-saves', '--offline', 'config'])
def test_sync_can_be_turned_off(cloud_game, off):
    home, _ = cloud_game
    if off == 'config':
        (home / 'config.ini').write_text('[Heirloom]\ndisable_cloud_save_sync = true\n')
    result = launch('ok', *([] if off == 'config' else [off]))
    assert result.stdout == ''
    assert not (home / 'save-backups').exists()


def test_failed_sync_still_launches_the_game(cloud_game):
    result = launch('broken')
    assert result.stdout == ''
    assert 'Syncing the cloud save of "Fish Game" failed' in result.stderr
    assert "ConnectionError('no route to Epic')" in result.stderr


def test_unknown_save_folder_is_left_alone(cloud_game):
    home, _ = cloud_game
    set_save_folder(home, '{SomethingNew}/Saves')
    result = launch('ok')
    assert result.stdout == ''
    assert 'the save folder of "Fish Game" is not known' in result.stderr
    assert not json.loads((home / 'installed.json').read_text())['Fish'].get('save_path')


def test_backup_keeps_only_cloud_save_files_and_replaces_the_last_copy(fake_game, tmp_path):
    (fake_game / 'metadata' / 'Fish.json').write_text(json.dumps({
        'app_name': 'Fish', 'app_title': 'Fish Game', 'asset_infos': {},
        'metadata': {'customAttributes': {'CloudSaveFolder': {'type': 'STRING', 'value': '{InstallDir}'},
                                          'CloudIncludeList': {'type': 'STRING', 'value': 'slots/'}}}}))
    save_dir = tmp_path / 'save'
    (save_dir / 'slots').mkdir(parents=True)
    (save_dir / 'slots' / 'one.sav').write_text('one')
    (save_dir / 'settings.ini').write_text('not part of the cloud save')
    backup = tmp_path / 'backup'
    (backup / 'slots').mkdir(parents=True)
    (backup / 'slots' / 'older.sav').write_text('from the last download')

    HeirloomCore().backup_saves('Fish', str(save_dir), backup)

    assert sorted(path.relative_to(backup).as_posix() for path in backup.rglob('*') if path.is_file()) == \
        ['slots/one.sav']
    assert (backup / 'slots' / 'one.sav').read_text() == 'one'
