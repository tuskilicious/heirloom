import hashlib
import io
import json
import os
import sys

import pytest

from legendary.lfs.lgndry import LGDLFS
from legendary.lfs.utils import (
    LockedJSONData,
    delete_filelist,
    get_dir_size,
    validate_files,
)
from legendary.lfs.wine_helpers import (
    case_insensitive_file_search,
    case_insensitive_path_search,
    get_shell_folders,
    read_registry,
)
from legendary.models.config import LGDConf
from legendary.models.game import Game, InstalledGame, VerifyResult


def _sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def test_delete_filelist_removes_files_and_emptied_dirs(tmp_path):
    (tmp_path / 'a' / 'b').mkdir(parents=True)
    (tmp_path / 'a' / 'b' / 'x.bin').write_bytes(b'x')
    (tmp_path / 'top.txt').write_bytes(b't')

    assert delete_filelist(str(tmp_path), ['a/b/x.bin', 'top.txt'])
    assert list(tmp_path.iterdir()) == []


def test_delete_filelist_reports_missing(tmp_path):
    assert not delete_filelist(str(tmp_path), ['ghost.txt'], silent=True)


def test_delete_filelist_root(tmp_path):
    root = tmp_path / 'game'
    root.mkdir()
    (root / 'f').write_bytes(b'')
    delete_filelist(str(root), ['f'], delete_root_directory=True)
    assert not root.exists()


def test_validate_files(tmp_path):
    (tmp_path / 'good').write_bytes(b'good')
    (tmp_path / 'bad').write_bytes(b'bad')
    results = {path: result for result, path, *_ in validate_files(
        str(tmp_path), [('good', _sha1(b'good')), ('bad', _sha1(b'other')), ('gone', '')])}
    assert results == {'good': VerifyResult.HASH_MATCH, 'bad': VerifyResult.HASH_MISMATCH,
                       'gone': VerifyResult.FILE_MISSING}


def test_validate_files_large_file_progress(tmp_path, monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr('legendary.lfs.utils.stdout', out)
    data = b'x' * 4096
    (tmp_path / 'big').write_bytes(data)
    [(result, _, _, size)] = validate_files(str(tmp_path), [('big', _sha1(data))], large_file_threshold=1)
    assert (result, size) == (VerifyResult.HASH_MATCH, 4096)
    assert 'Verifying large file' in out.getvalue()


def test_validate_files_rejects_bad_input(tmp_path):
    with pytest.raises(ValueError):
        list(validate_files(str(tmp_path), []))
    with pytest.raises(OSError):
        list(validate_files(str(tmp_path / 'nope'), [('a', '')]))


def test_dir_size(tmp_path):
    (tmp_path / 'd').mkdir()
    (tmp_path / 'd' / 'a').write_bytes(b'123')
    (tmp_path / 'b').write_bytes(b'45')
    assert get_dir_size(str(tmp_path)) == 5


def test_locked_json_data(tmp_path):
    path = tmp_path / 'data.json'
    with LockedJSONData(str(path)) as lock:
        assert lock.data is None
        lock.data = {'k': 1}
    assert json.loads(path.read_text()) == {'k': 1}

    with LockedJSONData(str(path)) as lock:
        assert lock.data == {'k': 1}
        with pytest.raises(ValueError):
            lock.data = None
        lock.clear()
    assert not path.exists()


@pytest.mark.skipif(sys.platform == 'win32', reason='no-op on case-insensitive Windows filesystems')
def test_case_insensitive_file_search(tmp_path):
    (tmp_path / 'Game' / 'Binaries').mkdir(parents=True)
    (tmp_path / 'Game' / 'Binaries' / 'Run.EXE').write_bytes(b'')
    found = case_insensitive_file_search(str(tmp_path / 'game' / 'binaries' / 'run.exe'))
    assert found == str(tmp_path / 'Game' / 'Binaries' / 'Run.EXE')
    missing = case_insensitive_file_search(str(tmp_path / 'game' / 'nothere' / 'x'))
    assert missing == str(tmp_path / 'Game' / 'nothere' / 'x')


@pytest.mark.skipif(sys.platform == 'win32', reason='resolves POSIX-style absolute paths')
def test_case_insensitive_path_search(tmp_path):
    (tmp_path / 'Saves' / 'Slot1').mkdir(parents=True)
    found = case_insensitive_path_search(str(tmp_path / 'saves' / 'SLOT1' / 'new'))
    assert found == os.path.realpath(tmp_path / 'Saves' / 'Slot1' / 'new')


def test_wine_registry_shell_folders(tmp_path):
    (tmp_path / 'user.reg').write_text(
        'WINE REGISTRY Version 2\n'
        '[Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Explorer\\\\Shell Folders] 1700000000\n'
        '"AppData"="C:\\\\users\\\\me\\\\AppData\\\\Roaming"\n')
    folders = get_shell_folders(read_registry(str(tmp_path)), str(tmp_path))
    assert folders['AppData'] == os.path.join(str(tmp_path), 'drive_c', 'users/me/AppData/Roaming')


def test_lgdconf_tracks_modification_and_read_only(tmp_path):
    conf = LGDConf()
    conf.set('Sec', 'Key', 'v')
    assert conf.modified and conf['Sec']['Key'] == 'v'

    path = tmp_path / 'c.ini'
    with path.open('w') as f:
        conf.write(f)
    assert not conf.modified

    fresh = LGDConf()
    fresh.read(str(path))
    assert fresh.modtime == int(path.stat().st_mtime)
    fresh.read_only = True
    fresh.set('Sec', 'Key', 'changed')
    assert fresh['Sec']['Key'] == 'v'
    assert fresh.remove_option('Sec', 'Key') is False


def test_lgdlfs_creates_layout_and_default_config(lgd_home):
    lgd = LGDLFS()
    assert str(lgd.path) == str(lgd_home)
    for sub in ('manifests', 'metadata', 'tmp'):
        assert (lgd_home / sub).is_dir()
    lgd.save_config()
    assert 'disable_update_check' in (lgd_home / 'config.ini').read_text()


def test_lgdlfs_custom_config_name_is_sanitised(lgd_home):
    lgd = LGDLFS(config_file='my:conf.ini')
    assert str(lgd.config_path) == str(lgd_home / 'myconf.ini')


def test_lgdlfs_installed_games_persist(lgd_home):
    lgd = LGDLFS()
    assert lgd.get_installed_list() == []
    game = InstalledGame(app_name='Fish', install_path='/games/fish', title='Fish', version='1.0')
    lgd.set_installed_game('Fish', game)

    reloaded = LGDLFS()
    assert reloaded.get_installed_game('Fish') == game
    reloaded.remove_installed_game('Fish')
    reloaded.remove_installed_game('Fish')
    assert LGDLFS().get_installed_game('Fish') is None


def test_lgdlfs_manifests(lgd_home):
    class FakeManifest:
        def write(self, f):
            f.write(b'manifest')

    lgd = LGDLFS()
    lgd.save_manifest('App', FakeManifest(), 'v1', platform='Mac')
    assert lgd.load_manifest('App', 'v1', platform='Mac') == b'manifest'
    assert lgd.load_manifest('App', 'v2') is None

    (lgd_home / 'manifests' / 'App_v0.manifest').write_bytes(b'legacy')
    assert lgd.load_manifest('App', 'v0') == b'legacy'

    lgd.clean_manifests([('App', 'v1', 'Mac')])
    assert sorted(p.name for p in (lgd_home / 'manifests').iterdir()) == ['App_Mac_v1.manifest']


def test_lgdlfs_game_meta_and_aliases(lgd_home):
    lgd = LGDLFS()
    lgd.set_game_meta('Fish', Game(app_name='Fish', app_title='Grand Theft Auto V'))
    lgd.set_game_meta('Dlc', Game(app_name='Dlc', app_title='Some DLC', metadata={'mainGameItem': {}}))
    assert lgd.get_game_app_names() == ['Dlc', 'Fish']
    lgd.generate_aliases()

    reloaded = LGDLFS()
    assert reloaded.get_game_meta('Fish').app_title == 'Grand Theft Auto V'
    assert reloaded.aliases['gta5'] == 'Fish'
    assert 'some dlc' not in reloaded.aliases

    reloaded.clean_metadata(['Fish'])
    assert [p.name for p in (lgd_home / 'metadata').iterdir()] == ['Fish.json']
    reloaded.delete_game_meta('Fish')
    with pytest.raises(ValueError):
        reloaded.delete_game_meta('Fish')


def test_lgdlfs_caches(lgd_home):
    lgd = LGDLFS()
    assert lgd.get_cached_version()['data'] is None
    lgd.set_cached_version({'v': 2})
    lgd.set_cached_sdl_data('App', 'sv', {'tags': []})
    lgd.set_cached_overlay_version({'o': 1})
    lgd.entitlements = [{'id': 1}]
    lgd.achievements = {'a': 1}

    fresh = LGDLFS()
    assert fresh.get_cached_version()['data'] == {'v': 2}
    assert fresh.get_cached_sdl_data('App') == {'version': 'sv', 'data': {'tags': []}}
    assert fresh.get_cached_overlay_version()['data'] == {'o': 1}
    assert fresh.entitlements == [{'id': 1}]
    assert fresh.achievements == {'a': 1}
    assert fresh.get_dir_size() > 0

    fresh.clean_tmp_data()
    assert fresh.get_cached_sdl_data('App') is None
    assert list((lgd_home / 'tmp').iterdir()) == []


def test_lgdlfs_userdata_lock(lgd_home):
    lgd = LGDLFS()
    assert lgd.userdata is None
    with lgd.userdata_lock as lock:
        lock.data = {'account_id': 'abc'}
    assert LGDLFS().userdata == {'account_id': 'abc'}
    lgd.invalidate_userdata()
    assert not (lgd_home / 'user.json').exists()


def test_lgdlfs_overlay_info(lgd_home):
    lgd = LGDLFS()
    assert lgd.get_overlay_install_info() is None
    info = InstalledGame(app_name='overlay', install_path='/o', title='Overlay', version='1')
    lgd.set_overlay_install_info(info)
    assert LGDLFS().get_overlay_install_info() == info
    lgd.remove_overlay_install_info()
    assert LGDLFS().get_overlay_install_info() is None


def test_lgdlfs_backs_up_externally_modified_config(lgd_home):
    lgd = LGDLFS()
    lgd.save_config()
    config = lgd_home / 'config.ini'
    os.utime(config, (1_000_000, 1_000_000))
    lgd.config.set('Legendary', 'log_level', 'debug')
    lgd.save_config()
    assert (lgd_home / 'config.1000000.ini').exists()
    assert 'log_level' in config.read_text()


def test_lgdlfs_migrates_old_manifest_folder(lgd_home):
    old = lgd_home / 'manifests' / 'old'
    old.mkdir(parents=True)
    (old / 'App_v1.manifest').write_bytes(b'')
    (lgd_home / 'manifests' / 'App.manifest').write_bytes(b'')
    LGDLFS()
    assert sorted(p.name for p in (lgd_home / 'manifests').iterdir()) == ['App_v1.manifest']
