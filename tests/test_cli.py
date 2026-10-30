import json
import locale
import subprocess
import sys


def run(*args):
    result = subprocess.run([sys.executable, '-m', 'heirloom.cli', *args], capture_output=True, timeout=120)
    # heirloom writes UTF-8 to stdout whenever it is not a terminal; stderr uses the system encoding
    result.stdout = result.stdout.decode('utf-8')
    result.stderr = result.stderr.decode(locale.getpreferredencoding(False), errors='replace')
    return result


def test_version():
    result = run('--version')
    assert result.returncode == 0
    assert 'heirloom version' in result.stdout


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


def test_move_a_game_and_fail_when_its_folder_is_taken(fake_game, tmp_path):
    games = tmp_path / 'Games'
    result = run('move', 'Fish', str(games))
    assert result.returncode == 0, result.stderr
    assert (games / 'FishGame').is_dir() and not (tmp_path / 'FishGame').exists()
    assert json.loads((fake_game / 'installed.json').read_text())['Fish']['install_path'] == str(games / 'FishGame')

    (tmp_path / 'Taken' / 'FishGame').mkdir(parents=True)
    result = run('move', 'Fish', str(tmp_path / 'Taken'))
    assert result.returncode == 1, 'the window shows it failed'
    assert (games / 'FishGame').is_dir(), 'left where it was'
