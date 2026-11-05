"""What Linux and Mac do for a desktop program. Their modules import anywhere, so most of this is tested on any system."""
import plistlib
import subprocess
import sys
import time

import pytest

from heirloom.desktop import linux, macos, shared

posix = pytest.mark.skipif(sys.platform == 'win32', reason='runs real shell scripts')


def test_games_dont_inherit_the_bundled_files(monkeypatch):
    bundle = '/tmp/.mount_x/_internal'
    monkeypatch.setattr(sys, '_MEIPASS', bundle, raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', f'{bundle}:/usr/local/lib')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/usr/local/lib')
    monkeypatch.setenv('QT_PLUGIN_PATH', f'{bundle}/PySide6/Qt/plugins')
    monkeypatch.setenv('WINEPREFIX', '/home/me/.wine')
    env = shared.host_env()
    assert env['LD_LIBRARY_PATH'] == '/usr/local/lib', 'what it was before PyInstaller changed it'
    assert 'LD_LIBRARY_PATH_ORIG' not in env and 'QT_PLUGIN_PATH' not in env
    assert env['WINEPREFIX'] == '/home/me/.wine', 'the rest stays'

    monkeypatch.delenv('LD_LIBRARY_PATH_ORIG')
    assert 'LD_LIBRARY_PATH' not in shared.host_env(), 'and with nothing to go back to, none at all'


def test_outside_a_bundle_the_environment_is_left_alone(monkeypatch):
    monkeypatch.delattr(sys, '_MEIPASS', raising=False)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/mine')
    assert shared.host_env()['LD_LIBRARY_PATH'] == '/mine'


@pytest.fixture
def appimage(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path / 'config'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    folder = tmp_path / 'my games $folder'
    folder.mkdir()
    path = folder / 'heirloom.AppImage'
    path.write_text('old')
    monkeypatch.setenv('APPIMAGE', str(path))
    monkeypatch.setenv('APPDIR', str(tmp_path / 'appdir'))
    (tmp_path / 'appdir').mkdir()
    (tmp_path / 'appdir' / 'heirloom.png').write_bytes(b'icon')
    return path


def test_the_appimage_adds_itself_to_the_menu_and_follows_a_move(appimage, tmp_path, monkeypatch):
    linux.add_to_menu()
    entry = tmp_path / 'data' / 'applications' / 'heirloom.desktop'
    exec_line = 'Exec="' + str(appimage).replace('\\', '\\\\').replace('$', '\\$') + '"\n'
    assert exec_line in entry.read_text(encoding='utf-8'), 'quoted as a desktop file wants'
    assert (tmp_path / 'data' / 'icons' / 'hicolor' / '256x256' / 'apps' / 'heirloom.png').read_bytes() == b'icon'

    linux.start_at_login(True)
    assert linux.starts_at_login() and linux.startup_command() is not None
    start = tmp_path / 'config' / 'autostart' / 'heirloom.desktop'
    assert 'gui --background\n' in start.read_text(encoding='utf-8')

    moved = appimage.with_name('moved.AppImage')
    appimage.rename(moved)
    monkeypatch.setenv('APPIMAGE', str(moved))
    linux.add_to_menu()
    assert 'moved.AppImage' in entry.read_text(encoding='utf-8')
    assert 'moved.AppImage' in start.read_text(encoding='utf-8'), 'starting at login follows it too'

    linux.start_at_login(False)
    assert not linux.starts_at_login()


def test_without_an_appimage_nothing_is_added(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.delenv('APPIMAGE', raising=False)
    linux.add_to_menu()
    assert not list(tmp_path.iterdir())
    assert not linux.opens_window_by_default() and not linux.can_update_itself() and linux.update_blocker() == ''
    with pytest.raises(ValueError):
        linux.start_at_login(True)


def test_linux_lists_what_can_run_windows_games(monkeypatch):
    monkeypatch.setattr(linux.shutil, 'which', lambda name: f'/usr/bin/{name}' if name == 'wine' else None)
    assert linux.game_runners() == ['/usr/bin/wine']


def install_script(script: str, **env: str) -> None:
    subprocess.run(['sh', '-c', script], env=env, check=True, timeout=30)


@posix
def test_a_new_appimage_replaces_the_old_and_reopens(tmp_path):
    target, setup, log = tmp_path / 'heirloom.AppImage', tmp_path / 'new', tmp_path / 'log'
    setup.write_text(f'#!/bin/sh\necho "new $@" > "{log}"\n')
    target.write_text('old')
    install_script(linux.INSTALL, HL_SETUP=str(setup), HL_TARGET=str(target), HL_REOPEN='1', PATH='/usr/bin:/bin')
    assert log.read_text() == 'new gui --background\n'
    assert not target.with_name('heirloom.AppImage.new').exists()


@posix
def test_without_a_tray_a_new_appimage_doesnt_reopen(tmp_path):
    target, setup = tmp_path / 'heirloom.AppImage', tmp_path / 'new'
    setup.write_text('new')
    target.write_text('old')
    install_script(linux.INSTALL, HL_SETUP=str(setup), HL_TARGET=str(target), HL_REOPEN='', PATH='/usr/bin:/bin')
    assert target.read_text() == 'new'


@posix
def test_a_failed_copy_keeps_the_old_appimage(tmp_path):
    target, log = tmp_path / 'heirloom.AppImage', tmp_path / 'log'
    target.write_text(f'#!/bin/sh\necho "old $@" > "{log}"\n')
    target.chmod(0o755)
    install_script(linux.INSTALL, HL_SETUP=str(tmp_path / 'missing'), HL_TARGET=str(target), HL_REOPEN='1',
                   PATH='/usr/bin:/bin')
    assert log.read_text() == 'old gui --background\n', 'and that one reopens'


@posix
def test_installing_waits_for_heirloom_to_quit(tmp_path):
    done = tmp_path / 'done'
    program = ('import time; from heirloom.desktop.shared import run_after_quitting; '
               f'run_after_quitting(\'touch "$HL_DONE"\', {{"HL_DONE": {str(done)!r}}}); time.sleep(3)')
    process = subprocess.Popen([sys.executable, '-c', program])
    time.sleep(1.5)
    assert not done.exists(), 'not while it is still running'
    process.wait(30)
    deadline = time.monotonic() + 10
    while not done.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert done.exists()


@pytest.fixture
def mac_app(tmp_path, monkeypatch):
    program = tmp_path / 'Applications' / 'Heirloom.app' / 'Contents' / 'MacOS' / 'heirloom'
    program.parent.mkdir(parents=True)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(program))
    monkeypatch.setattr(macos.Path, 'home', lambda: tmp_path)
    return program


def test_the_mac_app_starts_at_login_with_a_launch_agent(mac_app, tmp_path):
    assert macos.opens_window_by_default() and not macos.starts_at_login()
    macos.start_at_login(True)
    agent = tmp_path / 'Library' / 'LaunchAgents' / f'{macos.LAUNCH_AGENT}.plist'
    assert plistlib.loads(agent.read_bytes())['ProgramArguments'] == [str(mac_app), 'gui', '--background']
    assert macos.starts_at_login()
    macos.start_at_login(False)
    assert not agent.exists()


def test_a_mac_app_run_from_downloads_says_to_move(mac_app, tmp_path, monkeypatch):
    assert macos.can_update_itself() and macos.update_blocker() == ''
    translocated = tmp_path / 'AppTranslocation' / 'x' / 'd' / 'Heirloom.app' / 'Contents' / 'MacOS' / 'heirloom'
    monkeypatch.setattr(sys, 'executable', str(translocated))
    assert not macos.can_update_itself()
    assert 'Applications' in macos.update_blocker()


def test_outside_a_mac_app_there_is_nothing_to_update(monkeypatch):
    monkeypatch.delattr(sys, 'frozen', raising=False)
    assert not macos.can_update_itself() and macos.update_blocker() == '' and macos.startup_command() is None
