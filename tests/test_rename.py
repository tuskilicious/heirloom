"""Coming from Legendary: its config folder, config sections and environment variables keep working."""
import json
import shutil

import pytest

from heirloom.lfs import lgndry
from heirloom.lfs.lgndry import config_dir, migrate_legendary_config

from .test_cli import run


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    for variable in ('HEIRLOOM_CONFIG_PATH', 'LEGENDARY_CONFIG_PATH'):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path))
    return tmp_path


def test_config_dir_prefers_heirloom_then_legendary_variable(config_home, monkeypatch, tmp_path):
    assert config_dir() == config_home / 'heirloom'
    monkeypatch.setenv('LEGENDARY_CONFIG_PATH', str(tmp_path / 'old'))
    assert config_dir() == tmp_path / 'old'
    monkeypatch.setenv('HEIRLOOM_CONFIG_PATH', str(tmp_path / 'new'))
    assert config_dir() == tmp_path / 'new'


def legendary_setup(config_home):
    old = config_home / 'legendary'
    (old / 'tmp').mkdir(parents=True)
    (old / 'running').mkdir()
    (old / 'tmp' / 'Fish.resume').write_text('partial download')
    (old / 'running' / 'Fish-1.lock').write_text('')
    (old / 'installed.json').write_text(json.dumps({'Fish': {
        'app_name': 'Fish', 'title': 'Fish Game', 'version': '1', 'install_path': '/games/fish',
        'install_size': 1024}}))
    (old / 'config.ini').write_text('[Legendary]\nlog_level = debug\ntheme = modern\n\n'
                                    '[Legendary.aliases]\nfishy = Fish\n')
    return old


def test_first_run_copies_legendary_data_and_renames_config_sections(config_home):
    old = legendary_setup(config_home)
    old_files = {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()}

    result = run('list-installed')
    assert result.returncode == 0, result.stderr
    assert 'Fish Game' in result.stdout
    assert 'Copied your Legendary data' in result.stderr

    new = config_home / 'heirloom'
    assert not (new / 'tmp' / 'Fish.resume').exists() and not (new / 'running').exists()
    config = (new / 'config.ini').read_text()
    assert '[Heirloom]' in config and '[Heirloom.aliases]' in config and '[Legendary' not in config
    assert 'theme = modern' in config and 'fishy = Fish' in config

    assert {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()} == old_files, \
        "Legendary's own folder is left as it was"
    assert 'Copied your Legendary data' not in run('list-installed').stderr, 'copied only once'


def test_existing_heirloom_folder_is_left_alone(config_home, caplog):
    legendary_setup(config_home)
    (config_home / 'heirloom').mkdir()
    (config_home / 'heirloom' / 'config.ini').write_text('[Heirloom]\n')
    migrate_legendary_config()
    assert [p.name for p in (config_home / 'heirloom').iterdir()] == ['config.ini']
    assert sorted(p.name for p in config_home.iterdir()) == ['heirloom', 'legendary'], 'nothing is copied'
    assert not caplog.records


def test_failed_copy_leaves_nothing_half_copied(config_home, monkeypatch):
    legendary_setup(config_home)
    real_copytree = shutil.copytree

    def copy_then_fail(source, destination, **kwargs):
        destination.mkdir(parents=True)
        (destination / 'installed.json').write_text('{}')
        raise OSError('disk full')

    monkeypatch.setattr(lgndry.shutil, 'copytree', copy_then_fail)
    migrate_legendary_config()
    assert sorted(p.name for p in config_home.iterdir()) == ['legendary']
    monkeypatch.setattr(lgndry.shutil, 'copytree', real_copytree)
    migrate_legendary_config()
    assert (config_home / 'heirloom' / 'installed.json').exists(), 'the next run tries again'


def test_legendary_wrapper_variable_still_works(fake_game, monkeypatch):
    monkeypatch.setenv('LEGENDARY_WRAPPER_EXE', 'my-wrapper')
    result = run('launch', 'Fish', '--offline', '--dry-run')
    assert result.returncode == 0, result.stderr
    assert 'Launch parameters: my-wrapper ' in result.stderr
