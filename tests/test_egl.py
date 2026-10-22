import configparser
import json
import sys

import pytest

from heirloom.core import HeirloomCore
from heirloom.lfs.egl import EPCLFS, read_v2_installations
from heirloom.models.egl import EGLManifest
from heirloom.utils.savegame_helper import SaveGameHelper

from .test_cli import run
from .test_formats import _make_save


def record(installation_id, app_name, game_dir, **fields):
    return {'installationId': installation_id, 'artifactId': app_name, 'dir': str(game_dir), 'complete': True,
            'platform': 'Windows', 'namespace': 'ns', 'itemId': f'{app_name}-item', 'version': '1',
            'tags': [''], 'launchExecutable': 'Bin/game.exe', 'launchCommand': '-fast',
            'writtenAt': '2026-10-21T00:00:00Z', **fields}


def write_installations(path, *records, trailing=''):
    lines = [json.dumps({'version': 1, 'writtenAt': '2026-10-21T00:00:00Z', 'entries': len(records)})]
    lines += [json.dumps(r) for r in records]
    path.write_text('\n'.join(lines) + '\n' + trailing, encoding='utf-8')
    return path


@pytest.fixture
def no_real_launcher(tmp_path, monkeypatch):
    """Keeps EPCLFS from finding this machine's real Epic Games Launcher data"""
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'localappdata'))
    monkeypatch.setenv('PROGRAMDATA', str(tmp_path / 'programdata'))


def test_installations_log_is_folded_to_current_installs(tmp_path):
    path = write_installations(
        tmp_path / 'installations.jsonl',
        record('AAA', 'Fish', tmp_path / 'Fish', version='1'),
        record('BBB', 'Cat', tmp_path / 'Cat', complete=False),
        record('CCC', 'Dog', tmp_path / 'Dog'),
        record('AAA', 'Fish', tmp_path / 'Fish', version='2'),
        record('DDD', 'FishDLC', tmp_path / 'Fish', parentInstallationId='AAA'),
        record('EEE', 'Orphan', tmp_path / 'Orphan', parentInstallationId='GONE'),
        record('FFF', 'MacGame', tmp_path / 'Mac', platform='Mac'),
        {'installationId': 'CCC', 'deleted': True, 'writtenAt': '2026-10-21T01:00:00Z'},
        trailing='{"installationId": "HHH", "artif',
    )

    manifests = read_v2_installations(path)

    assert set(manifests) == {'Fish', 'FishDLC', 'Orphan'}, 'incomplete, uninstalled and Mac installs are skipped'
    assert manifests['Fish'].app_version_string == '2', 'the latest record wins'
    assert manifests['Fish'].main_game_appname == 'Fish'
    assert manifests['FishDLC'].main_game_appname == 'Fish', 'DLC points at its parent game'
    assert manifests['Orphan'].main_game_appname == '', 'DLC whose parent is gone is not treated as a game'


def test_record_maps_onto_egl_manifest(tmp_path):
    manifest = EGLManifest.from_v2_installation(record('AAA', 'Fish', tmp_path / 'Fish', tags=['', 'hd']), 'Fish')

    assert (manifest.installation_guid, manifest.install_location, manifest.install_tags) == \
        ('AAA', str(tmp_path / 'Fish'), ['', 'hd'])
    assert (manifest.executable, manifest.launch_command) == ('Bin/game.exe', '-fast')
    assert (manifest.catalog_item_id, manifest.namespace) == ('Fish-item', 'ns')
    igame = manifest.to_lgd_igame()
    assert (igame.title, igame.install_size, igame.can_run_offline, igame.requires_ot) == (None,) * 4, \
        'details the new launcher does not record stay unknown for the importer to fill in'


def test_old_launcher_manifests_still_read_and_written(tmp_path, no_real_launcher):
    manifests_dir = tmp_path / 'Manifests'
    manifests_dir.mkdir()
    item = EGLManifest.from_v2_installation(record('AAA', 'Fish', tmp_path / 'Fish'), 'Fish')
    item.display_name, item.install_size, item.ownership_token, item.can_run_offline = 'Fish Game', 5, False, True
    (manifests_dir / 'AAA.item').write_text(json.dumps(item.to_json()))

    egl = EPCLFS()
    egl.programdata_path = str(manifests_dir)
    assert egl.installations_path is None
    assert egl.get_manifest('Fish').display_name == 'Fish Game'

    item.app_name, item.installation_guid = 'Cat', 'BBB'
    egl.set_manifest(item)
    assert (manifests_dir / 'BBB.item').exists()
    egl.delete_manifest('Fish')
    assert not (manifests_dir / 'AAA.item').exists()


def test_new_launcher_install_list_is_never_written(tmp_path, no_real_launcher):
    path = write_installations(tmp_path / 'installations.jsonl', record('AAA', 'Fish', tmp_path / 'Fish'))
    before = path.read_bytes()
    old_manifests = tmp_path / 'Manifests'
    old_manifests.mkdir()
    egl = EPCLFS()
    egl.installations_path, egl.programdata_path = str(path), str(old_manifests)

    with pytest.raises(ValueError):
        egl.set_manifest(egl.get_manifest('Fish'))
    with pytest.raises(ValueError):
        egl.delete_manifest('Fish')
    assert path.read_bytes() == before
    assert not any(old_manifests.iterdir()), 'nothing is exported to the old launcher folder either'


@pytest.mark.skipif(sys.platform != 'win32', reason='the new launcher is only looked for on Windows')
def test_new_launcher_is_detected_once_the_old_one_is_gone(tmp_path, no_real_launcher):
    eglv2 = tmp_path / 'localappdata' / 'com.epicgames.eglv2'
    eglv2.mkdir(parents=True)
    write_installations(eglv2 / 'installations.jsonl')
    assert EPCLFS().installations_path == str(eglv2 / 'installations.jsonl')

    (tmp_path / 'programdata' / 'Epic' / 'EpicGamesLauncher' / 'Data' / 'Manifests').mkdir(parents=True)
    assert EPCLFS().installations_path is None, 'the old launcher keeps being used while its manifests exist'


def test_sync_from_the_old_launcher_stays_off_with_the_new_one(tmp_path, lgd_home, no_real_launcher):
    path = write_installations(tmp_path / 'installations.jsonl')
    lgd_home.mkdir()
    (lgd_home / 'config.ini').write_text(f'[Heirloom]\negl_sync = true\negl_installations = {path}\n')

    core = HeirloomCore()
    assert core.egl.installations_path == str(path)
    assert not core.egl_sync_enabled, 'an old "egl_sync = true" must not make Heirloom export to or sync with it'


@pytest.fixture
def new_launcher_game(lgd_home, tmp_path, no_real_launcher):
    """A game installed by the new launcher (with its .egstore manifest) that Heirloom knows about"""
    game_dir = tmp_path / 'FishGame'
    files = _make_save(game_dir)
    out = SaveGameHelper().package_savegame(str(game_dir))
    blob = out[next(name for name in out if name.startswith('manifests/'))]
    blob.seek(0)
    (game_dir / '.egstore').mkdir()
    (game_dir / '.egstore' / 'AAA.manifest').write_bytes(blob.read())

    lgd_home.mkdir()
    (lgd_home / 'assets.json').write_text(json.dumps({'Windows': [
        {'app_name': 'Fish', 'namespace': 'ns', 'catalog_item_id': 'Fish-item', 'build_version': '2'}]}))
    (lgd_home / 'metadata').mkdir()
    (lgd_home / 'metadata' / 'Fish.json').write_text(json.dumps({
        'app_name': 'Fish', 'app_title': 'Fish Game', 'asset_infos': {},
        'metadata': {'customAttributes': {'CanRunOffline': {'value': 'false'},
                                          'OwnershipToken': {'value': 'True'}}}}))
    installations = write_installations(tmp_path / 'installations.jsonl',
                                        record('AAA', 'Fish', game_dir, version='2'))
    return installations, game_dir, sum(len(data) for data in files.values())


def test_egl_sync_imports_from_the_new_launcher(new_launcher_game, lgd_home):
    installations, game_dir, install_size = new_launcher_game

    result = run('egl-sync', '--import-only', '--yes', '--egl-installations', str(installations))
    assert result.returncode == 0, result.stderr
    assert 'Fish - Fish Game' in result.stdout
    assert 'not supported yet' in result.stdout

    igame = json.loads((lgd_home / 'installed.json').read_text())['Fish']
    assert (igame['title'], igame['version'], igame['install_path'], igame['egl_guid']) == \
        ('Fish Game', '2', str(game_dir), 'AAA')
    assert igame['install_size'] == install_size, 'size comes from the manifest'
    assert (igame['can_run_offline'], igame['requires_ot']) == (False, True), 'flags come from the metadata'
    config = configparser.ConfigParser()
    config.read(lgd_home / 'config.ini')
    assert not config.has_option('Heirloom', 'egl_sync'), 'automatic sync is not switched on'
    assert config.get('Heirloom', 'egl_installations') == str(installations), 'the path is remembered'

    again = run('egl-sync', '--yes')
    assert again.returncode == 0, again.stderr
    assert 'Nothing to import' in again.stdout, 'games already in Heirloom are left as they are'
