"""
Cloud saves against an in-memory stand-in for Epic's save service: a save that goes up comes back byte for byte, a
download that fails leaves the save on the disk alone, cleaning up never deletes a working save, and the save folder
is found on each system.
"""
import contextlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import heirloom.core
from heirloom.core import HeirloomCore
from heirloom.models.game import SaveGameFile, SaveGameStatus

WHEN = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
MANIFEST = '2026.01.02-03.04.05.manifest'


class Response:
    def __init__(self, status_code: int, content: bytes = b''):
        self.status_code, self.content = status_code, content


class Cloud:
    """Epic's save service: each file at '<account>/savesync/<game>/<name>', read and written through a link"""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.user = {'account_id': 'abc'}
        self.unauth_session = self
        self.deleted: list[str] = []
        self.failing: set[str] = set()

    def path(self, app_name: str, name: str) -> str:
        return f'abc/savesync/{app_name}/{name}'

    def create_game_cloud_saves(self, app_name, names):
        return {'files': {name: {'writeLink': self.path(app_name, name)} for name in names}}

    def put(self, link, data):
        self.files[link] = data

    def get_user_cloud_saves(self, app_name='', manifests=False):
        return {'files': {path: {'readLink': path} for path in self.files
                          if not app_name or path.split('/')[2] == app_name}}

    def get(self, link):
        if link in self.failing:
            return Response(500)
        return Response(200, self.files[link]) if self.files.get(link) is not None else Response(404)

    def delete_game_cloud_save_file(self, path):
        self.deleted.append(path)
        self.files.pop(path, None)

    def chunks(self, app_name='Fish'):
        return [path for path in self.files if '.manifest' not in path and path.split('/')[2] == app_name]


def set_save_metadata(home: Path, app_name: str = 'Fish', **attributes: str) -> None:
    custom = {name: {'type': 'STRING', 'value': value} for name, value in attributes.items()}
    (home / 'metadata' / f'{app_name}.json').write_text(json.dumps({
        'app_name': app_name, 'app_title': app_name, 'asset_infos': {}, 'metadata': {'customAttributes': custom}}))


def write_files(folder: Path, files: dict[str, bytes]) -> None:
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)


def read_files(folder: Path) -> dict[str, bytes]:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


@pytest.fixture
def core(fake_game):
    set_save_metadata(fake_game, CloudSaveFolder='{InstallDir}/Saves', CloudExcludeList='*.tmp')
    core = HeirloomCore()
    core.egs = Cloud()
    return core


SAVE = {
    # more than a chunk's 1 MiB, so a file spans chunks
    'slots/one.sav': os.urandom(1500 * 1024),
    'slots/two.sav': b'two',
    'settings.ini': b'[x]\n',
}


def test_a_save_that_goes_up_comes_back_byte_for_byte(core, tmp_path):
    write_files(tmp_path / 'saves', SAVE | {'cache.tmp': b'not part of the save'})
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN)
    assert core.egs.path('Fish', f'manifests/{MANIFEST}') in core.egs.files
    assert len(core.egs.chunks()) == 2

    core.download_saves('Fish', manifest_name=MANIFEST, save_dir=str(tmp_path / 'restored'))
    assert read_files(tmp_path / 'restored') == SAVE, 'what the exclude list leaves out does not go up'
    assert abs((tmp_path / 'restored' / 'settings.ini').stat().st_mtime - WHEN.timestamp()) < 1, \
        'the files are dated when the save was made, which syncing compares'


def test_downloading_replaces_the_save_and_leaves_other_files(core, tmp_path):
    write_files(tmp_path / 'saves', SAVE)
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN)
    write_files(tmp_path / 'local', {'slots/one.sav': b'older progress', 'slots/three.sav': b'gone from the cloud',
                                     'cache.tmp': b'the game keeps this'})

    core.download_saves('Fish', manifest_name=MANIFEST, save_dir=str(tmp_path / 'local'), clean_dir=True)
    assert read_files(tmp_path / 'local') == SAVE | {'cache.tmp': b'the game keeps this'}


@pytest.mark.parametrize('failure', ['manifest fails', 'chunk fails', 'chunk missing', 'no connection'])
def test_a_download_that_fails_leaves_the_save_on_the_disk_alone(core, tmp_path, monkeypatch, failure):
    write_files(tmp_path / 'saves', SAVE)
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN)
    local = {'slots/one.sav': b'progress that exists only here', 'settings.ini': b'[mine]\n'}
    write_files(tmp_path / 'local', local)

    manifest = core.egs.path('Fish', f'manifests/{MANIFEST}')
    if failure == 'manifest fails':
        core.egs.failing.add(manifest)
    elif failure == 'chunk fails':
        core.egs.failing.add(core.egs.chunks()[0])
    elif failure == 'chunk missing':
        core.egs.files[core.egs.chunks()[0]] = None
    else:
        def no_connection(link):
            raise ConnectionError('no route to Epic')
        monkeypatch.setattr(core.egs, 'get', no_connection)

    with contextlib.suppress(ConnectionError):
        core.download_saves('Fish', manifest_name=MANIFEST, save_dir=str(tmp_path / 'local'), clean_dir=True)
    assert read_files(tmp_path / 'local') == local


def test_cleaning_up_removes_only_what_no_save_can_use(core, tmp_path):
    write_files(tmp_path / 'saves', SAVE)
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN)
    working = dict(core.egs.files)

    # a save whose manifest is gone, one with no chunks left, and a chunk nothing uses
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN + timedelta(days=1))
    no_manifest = core.egs.path('Fish', 'manifests/2026.01.03-03.04.05.manifest')
    core.egs.files[no_manifest] = None
    for chunk in set(core.egs.chunks()) - set(working):
        core.egs.files.pop(chunk)
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN + timedelta(days=2))
    no_chunks = core.egs.path('Fish', 'manifests/2026.01.04-03.04.05.manifest')
    for chunk in set(core.egs.chunks()) - set(working):
        core.egs.files.pop(chunk)
    orphan = core.egs.path('Fish', 'ChunksV4/00/0000000000000000_00000000000000000000000000000000.chunk')
    core.egs.files[orphan] = b'unused'

    # another game's save that can't be read just now: its chunks might be in use, so they stay
    set_save_metadata(core.lgd.path, 'Kart', CloudSaveFolder='{InstallDir}/Saves')
    unreadable = core.egs.path('Kart', f'manifests/{MANIFEST}')
    core.egs.files[unreadable] = b'?'
    core.egs.failing.add(unreadable)
    maybe_used = core.egs.path('Kart', 'ChunksV4/01/0000000000000001_00000000000000000000000000000001.chunk')
    core.egs.files[maybe_used] = b'?'

    core.clean_saves()
    assert sorted(core.egs.deleted) == sorted([no_manifest, no_chunks, orphan])
    assert all(path in core.egs.files for path in working), 'the working save is untouched'

    core.download_saves('Fish', manifest_name=MANIFEST, save_dir=str(tmp_path / 'restored'))
    assert read_files(tmp_path / 'restored') == SAVE, 'and still downloads'


def test_an_incomplete_save_goes_only_when_asked(core, tmp_path):
    write_files(tmp_path / 'saves', SAVE)
    core.upload_save('Fish', str(tmp_path / 'saves'), WHEN)
    core.egs.files.pop(core.egs.chunks()[0])
    manifest = core.egs.path('Fish', f'manifests/{MANIFEST}')

    core.clean_saves()
    assert manifest not in core.egs.deleted, 'part of it can still be downloaded'
    core.clean_saves(delete_incomplete=True)
    assert manifest in core.egs.deleted


def test_which_save_is_newer(core, tmp_path):
    folder = tmp_path / 'saves'
    folder.mkdir()
    cloud = SaveGameFile('Fish', 'x', MANIFEST)
    assert core.check_savegame_state(str(folder), None)[0] == SaveGameStatus.NO_SAVE
    assert core.check_savegame_state(str(folder), cloud)[0] == SaveGameStatus.REMOTE_NEWER

    write_files(folder, {'slot.sav': b'x'})
    assert core.check_savegame_state(str(folder), None)[0] == SaveGameStatus.LOCAL_NEWER
    for offset, state in ((30, SaveGameStatus.SAME_AGE), (3600, SaveGameStatus.LOCAL_NEWER),
                          (-3600, SaveGameStatus.REMOTE_NEWER)):
        os.utime(folder / 'slot.sav', (WHEN.timestamp() + offset,) * 2)
        assert core.check_savegame_state(str(folder), cloud)[0] == state, offset


def install_path(core) -> Path:
    return Path(core.lgd.get_installed_game('Fish').install_path)


@pytest.mark.skipif(os.name != 'nt', reason="the Windows variables only expand on Windows")
def test_the_save_folder_on_windows(core, tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('USERPROFILE', str(tmp_path / 'me'))
    for folder, expected in (('{InstallDir}/Saves/{EpicId}', install_path(core) / 'Saves' / 'abc'),
                             ('{AppData}\\Fish\\Saved', tmp_path / 'local' / 'Fish' / 'Saved'),
                             ('{UserDir}/My Games/Fish', tmp_path / 'me' / 'documents' / 'My Games' / 'Fish'),
                             ('{UserSavedGames}/Fish', tmp_path / 'me' / 'Saved Games' / 'Fish')):
        set_save_metadata(core.lgd.path, CloudSaveFolder=folder)
        assert Path(core.get_save_path('Fish')) == expected.resolve(), folder


def wine_prefix(path: Path, legacy: bool = False) -> Path:
    """A Wine prefix with the user.reg Wine writes, as an old prefix if legacy"""
    users = 'C:\\\\users\\\\me\\\\'
    folders = {'Personal': 'Documents', 'Local AppData': 'AppData\\\\Local',
               'AppData': 'Application Data' if legacy else 'AppData\\\\Roaming',
               '{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}': 'Saved Games',
               '{A520A1A4-1780-4FF6-BD18-167343C5AF16}': 'AppData\\\\LocalLow'}
    path.mkdir(parents=True)
    (path / 'user.reg').write_text('WINE REGISTRY Version 2\n'
                                   '[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Explorer\\\\Shell Folders]\n'
                                   + ''.join(f'"{name}"="{users}{value}"\n' for name, value in folders.items()))
    return path / 'drive_c' / 'users' / 'me'


@pytest.fixture
def linux(core, monkeypatch):
    monkeypatch.setattr(heirloom.core, 'sys_platform', 'linux')
    for name in ('WINEPREFIX', 'STEAM_COMPAT_DATA_PATH'):
        monkeypatch.delenv(name, raising=False)
    return core


def set_config(core, section: str, option: str, value: str) -> None:
    if not core.lgd.config.has_section(section):
        core.lgd.config.add_section(section)
    core.lgd.config.set(section, option, value)


@pytest.mark.parametrize('where', ['game', 'game env', 'default', 'proton', 'environment'])
def test_the_save_folder_in_a_wine_prefix(linux, tmp_path, monkeypatch, where):
    core = linux
    prefix = tmp_path / 'prefix'
    if where == 'game':
        set_config(core, 'Fish', 'wine_prefix', str(prefix))
        set_config(core, 'default', 'wine_prefix', str(tmp_path / 'not this one'))
    elif where == 'game env':
        set_config(core, 'Fish.env', 'WINEPREFIX', str(prefix))
    elif where == 'default':
        set_config(core, 'default', 'wine_prefix', str(prefix))
    elif where == 'proton':
        prefix = tmp_path / 'compat' / 'pfx'
        set_config(core, 'Fish.env', 'STEAM_COMPAT_DATA_PATH', str(tmp_path / 'compat'))
    else:
        monkeypatch.setenv('WINEPREFIX', str(prefix))
    user = wine_prefix(prefix)

    set_save_metadata(core.lgd.path, CloudSaveFolder='{AppData}/Fish/Saved')
    assert Path(core.get_save_path('Fish')) == (user / 'AppData' / 'Local' / 'Fish' / 'Saved').resolve()
    set_save_metadata(core.lgd.path, CloudSaveFolder='{UserSavedGames}/Fish')
    assert Path(core.get_save_path('Fish')) == (user / 'Saved Games' / 'Fish').resolve()


@pytest.mark.parametrize('legacy', [False, True])
def test_a_unity_save_folder_lands_in_locallow(linux, tmp_path, legacy):
    core = linux
    set_config(core, 'Fish', 'wine_prefix', str(tmp_path / 'prefix'))
    user = wine_prefix(tmp_path / 'prefix', legacy=legacy)
    # how Epic writes the save folder of a Unity game
    set_save_metadata(core.lgd.path, CloudSaveFolder='{AppData}/../LocalLow/Studio/Fish')
    assert Path(core.get_save_path('Fish')) == (user / 'AppData' / 'LocalLow' / 'Studio' / 'Fish').resolve()


def test_the_save_folder_of_a_mac_game(core, tmp_path, monkeypatch):
    monkeypatch.setattr(heirloom.core, 'sys_platform', 'darwin')
    monkeypatch.setattr(heirloom.core.Path, 'home', lambda: tmp_path / 'home')
    set_save_metadata(core.lgd.path, CloudSaveFolder='{AppData}/Fish', CloudSaveFolder_MAC='{AppData}/Fish Mac')
    assert Path(core.get_save_path('Fish', platform='Mac')) == \
        (tmp_path / 'home' / 'Library' / 'Application Support' / 'Fish Mac').resolve()


def test_a_game_without_cloud_saves_says_so(core):
    set_save_metadata(core.lgd.path)
    with pytest.raises(ValueError, match='does not support cloud saves'):
        core.get_save_path('Fish')
    with pytest.raises(ValueError, match='does not support cloud saves'):
        core.upload_save('Fish', '.')
