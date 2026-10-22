import json
import subprocess
import sys


def run(*args):
    return subprocess.run([sys.executable, '-m', 'legendary.cli', *args],
                          capture_output=True, text=True, timeout=120)


def test_version():
    result = run('--version')
    assert result.returncode == 0
    assert 'legendary version' in result.stdout


def test_list_installed_reads_install_db(lgd_home):
    lgd_home.mkdir()
    (lgd_home / 'installed.json').write_text(json.dumps({'Fish': {
        'app_name': 'Fish', 'title': 'Fish Game', 'version': '1.2', 'install_path': '/games/fish',
        'install_size': 1024 * 1024}}))
    result = run('list-installed')
    assert result.returncode == 0, result.stderr
    assert 'Fish Game' in result.stdout and 'Total: 1' in result.stdout


def test_status_offline(lgd_home):
    result = run('status', '--offline')
    assert result.returncode == 0, result.stderr
    assert 'Epic account: <not logged in>' in result.stdout
    assert str(lgd_home) in result.stdout


def launch_fish(monkeypatch, exit_code, *args):
    monkeypatch.setenv('EXIT_CODE', str(exit_code))
    return run('launch', 'Fish', '--offline', *args)
