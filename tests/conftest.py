import pytest


@pytest.fixture
def lgd_home(tmp_path, monkeypatch):
    home = tmp_path / 'legendary'
    monkeypatch.setenv('LEGENDARY_CONFIG_PATH', str(home))
    return home
