"""
What Heirloom plans before an install or update downloads anything: where the game goes, what it fetches (for an
update, only what changed), which server it uses, and what stops an install that can't work.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from heirloom.core import HeirloomCore
from heirloom.models.game import Game
from heirloom.models.manifest import Manifest
from heirloom.utils.savegame_helper import SaveGameHelper

# packed in name order into 1 MiB chunks, so the unchanged level fills a chunk of its own
LEVEL1 = os.urandom(1500 * 1024)
V1 = {'data/level1.pak': LEVEL1, 'data/level2.pak': b'two' * 100, 'Game.exe': b'exe1' * 1000,
      'readme.txt': b'hello'}
V2 = {'data/level1.pak': LEVEL1, 'data/level3.pak': b'three' * 100, 'Game.exe': b'exe2' * 1000,
      'readme.txt': b'hello'}


def build(folder: Path, files: dict[str, bytes], version: int) -> tuple[Path, Manifest]:
    """A build of the game: its files packed into chunks, and the manifest written where it can be read from"""
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    packed = SaveGameHelper().package_savegame(str(folder), manifest_dt=datetime(2026, 1, version, tzinfo=timezone.utc))
    blob = packed.pop(next(name for name in packed if name.startswith('manifests/')))
    blob.seek(0)
    data = blob.read()
    path = folder.with_suffix('.manifest')
    path.write_bytes(data)
    return path, Manifest.read_all(data)


def total_download(manifest: Manifest) -> int:
    return sum(chunk.file_size for chunk in manifest.chunk_data_list.elements)


@pytest.fixture
def builds(tmp_path):
    return build(tmp_path / 'v1', V1, 1), build(tmp_path / 'v2', V2, 2)


@pytest.fixture
def core(lgd_home):
    return HeirloomCore()


def game(**metadata) -> Game:
    custom = {'FolderName': {'value': 'Fish Folder'}, 'CanRunOffline': {'value': 'false'}}
    return Game(app_name='Fish', app_title='Fish Game', metadata={'customAttributes': custom} | metadata,
                base_urls=['https://akamai-a.example/Builds/Fish', 'https://fastly-b.example/Builds/Fish'])


def install(core, manifest: Manifest, folder: Path, files: dict[str, bytes]) -> None:
    """Fish installed: its files, and the record and manifest Heirloom keeps of the build that is there"""
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    (core.lgd.path / 'installed.json').write_text(json.dumps({'Fish': {
        'app_name': 'Fish', 'title': 'Fish Game', 'version': manifest.meta.build_version,
        'install_path': str(folder), 'executable': 'Game.exe', 'platform': 'Windows',
        'base_urls': ['https://akamai-a.example/Builds/Fish'], 'can_run_offline': True, 'install_size': 1}}))
    core.lgd.save_manifest('Fish', manifest, version=manifest.meta.build_version, platform='Windows')


def test_a_new_install_plans_every_file_into_the_game_folder(core, builds, tmp_path):
    (v1, m1), _ = builds
    dlm, analysis, igame = core.prepare_download(game(), override_manifest=str(v1), base_path=str(tmp_path / 'Games'))

    assert igame.install_path == str(tmp_path / 'Games' / 'Fish Folder'), 'the folder name Epic gives'
    assert (tmp_path / 'Games').is_dir() and not (tmp_path / 'Games' / 'Fish Folder').exists(), \
        'the games folder is made, and the game folder is left to the download'
    assert analysis.manifest_comparison.added == set(V1)
    assert analysis.install_size == sum(map(len, V1.values()))
    assert analysis.dl_size == total_download(m1)
    assert igame.version == m1.meta.build_version and not igame.can_run_offline
    assert Path(dlm.resume_file).name == 'Fish.resume', 'an interrupted install carries on'


def test_an_update_downloads_only_what_changed(core, builds, tmp_path):
    (_, m1), (v2, m2) = builds
    install(core, m1, tmp_path / 'Installed' / 'Fish', V1)
    _, analysis, igame = core.prepare_download(game(), override_manifest=str(v2), base_path=str(tmp_path / 'Other'))

    assert igame.install_path == str(tmp_path / 'Installed' / 'Fish'), 'where the game already is'
    comparison = analysis.manifest_comparison
    assert (comparison.changed, comparison.added, comparison.removed) == \
        ({'Game.exe'}, {'data/level3.pak'}, {'data/level2.pak'})
    assert comparison.unchanged == {'data/level1.pak', 'readme.txt'}
    assert 0 < analysis.dl_size < total_download(m2), 'the unchanged level is not fetched again'


def test_an_update_fetches_again_what_went_missing_from_the_disk(core, builds, tmp_path):
    (_, m1), (v2, _) = builds
    install(core, m1, tmp_path / 'Installed' / 'Fish', V1)
    (tmp_path / 'Installed' / 'Fish' / 'readme.txt').unlink()
    _, analysis, _ = core.prepare_download(game(), override_manifest=str(v2))
    assert 'readme.txt' in analysis.manifest_comparison.added


def test_repairing_checks_the_installed_build_rather_than_updating(core, builds, tmp_path):
    (_, m1), (v2, _) = builds
    install(core, m1, tmp_path / 'Installed' / 'Fish', V1)
    dlm, analysis, igame = core.prepare_download(game(), override_manifest=str(v2), repair=True)

    assert igame.version == m1.meta.build_version
    assert analysis.manifest_comparison.added == set(V1), 'every file is checked'
    assert Path(dlm.resume_file).name == 'Fish.repair'


@pytest.mark.parametrize(('preferred', 'https', 'chosen'), [
    ('', True, 'https://akamai-a.example/Builds/Fish'),
    ('fastly', True, 'https://fastly-b.example/Builds/Fish'),
    ('cloudflare', True, 'https://akamai-a.example/Builds/Fish'),
    ('fastly', False, 'http://fastly-b.example/Builds/Fish'),
])
def test_the_download_server(core, builds, tmp_path, preferred, https, chosen):
    (v1, _), _ = builds
    if preferred:
        core.lgd.config.set('Heirloom', 'preferred_cdn', preferred)
    dlm, _, _ = core.prepare_download(game(), override_manifest=str(v1), base_path=str(tmp_path / 'Games'),
                                      disable_https=not https)
    assert dlm.base_url == chosen


def test_dlc_needs_its_base_game(core, builds, tmp_path):
    (v1, _), _ = builds
    dlc = game(mainGameItem={'id': 'fish'})
    with pytest.raises(ValueError, match='base game'):
        core.prepare_download(dlc, override_manifest=str(v1), base_path=str(tmp_path / 'Games'))


@pytest.fixture
def planned(core, builds, tmp_path):
    (v1, _), _ = builds
    _, analysis, igame = core.prepare_download(game(), override_manifest=str(v1), base_path=str(tmp_path / 'Games'))
    return analysis, igame


def test_not_enough_space_stops_an_install_unless_told_to_go_ahead(planned):
    analysis, igame = planned
    analysis.disk_space_delta = 2 ** 60
    stopped = HeirloomCore.check_installation_conditions(analysis, igame, game())
    assert any('Not enough available disk space' in failure for failure in stopped.failures)
    allowed = HeirloomCore.check_installation_conditions(analysis, igame, game(), ignore_space_req=True)
    assert not allowed.failures and any('disk space' in warning for warning in allowed.warnings)

    analysis.disk_space_delta = 1
    assert not HeirloomCore.check_installation_conditions(analysis, igame, game()).failures


def test_a_games_folder_that_is_gone_stops_an_install(planned, tmp_path):
    analysis, igame = planned
    igame.install_path = str(tmp_path / 'unplugged drive' / 'Fish')
    result = HeirloomCore.check_installation_conditions(analysis, igame, game())
    assert any('does not exist' in failure for failure in result.failures)


def test_a_game_only_ubisoft_can_install_is_refused_but_its_updates_go_ahead(planned):
    analysis, igame = planned
    analysis.manifest_comparison.added = {'UplayInstaller.exe', 'data.bin'}
    first = HeirloomCore.check_installation_conditions(analysis, igame, game())
    assert any('Uplay' in failure for failure in first.failures)
    assert not HeirloomCore.check_installation_conditions(analysis, igame, game(), updating=True).failures


@pytest.mark.skipif(os.name == 'nt', reason='only a warning off Windows')
def test_anti_cheat_that_wine_cannot_run_is_warned_about(planned):
    analysis, igame = planned
    analysis.manifest_comparison.added = {'EasyAntiCheat/EasyAntiCheat_x64.dll', 'Game.exe'}
    result = HeirloomCore.check_installation_conditions(analysis, igame, game())
    assert any('EasyAntiCheat' in warning for warning in result.warnings) and not result.failures
