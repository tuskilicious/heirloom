import json
import sys

import pytest


@pytest.fixture(autouse=True)
def no_system_keyring(monkeypatch):
    """Tests never touch the real keyring, the ones about it set their own"""
    monkeypatch.setenv('PYTHON_KEYRING_BACKEND', 'keyring.backends.null.Keyring')


@pytest.fixture
def lgd_home(tmp_path, monkeypatch):
    home = tmp_path / 'heirloom'
    monkeypatch.setenv('HEIRLOOM_CONFIG_PATH', str(home))
    return home


@pytest.fixture
def fake_game(lgd_home, tmp_path):
    """An installed, offline-launchable game whose executable exits with the code in EXIT_CODE."""
    game_dir = tmp_path / 'FishGame'
    game_dir.mkdir()
    if sys.platform == 'win32':
        exe = game_dir / 'fish.cmd'
        exe.write_text('@ping -n 2 127.0.0.1 >nul\r\n@exit /b %EXIT_CODE%\r\n')
    else:
        exe = game_dir / 'fish.sh'
        exe.write_text('#!/bin/sh\nsleep 1\nexit "$EXIT_CODE"\n')
        exe.chmod(0o755)

    (lgd_home / 'metadata').mkdir(parents=True)
    (lgd_home / 'metadata' / 'Fish.json').write_text(json.dumps({
        'app_name': 'Fish', 'app_title': 'Fish Game', 'metadata': {}, 'asset_infos': {}}))
    (lgd_home / 'installed.json').write_text(json.dumps({'Fish': {
        'app_name': 'Fish', 'title': 'Fish Game', 'version': '1', 'install_path': str(game_dir),
        'executable': exe.name, 'platform': 'Linux', 'can_run_offline': True, 'install_size': 1024 ** 3}}))
    (lgd_home / 'user.json').write_text(json.dumps({'account_id': 'abc', 'displayName': 'Tester'}))
    return lgd_home
