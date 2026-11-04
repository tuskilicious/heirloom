"""
Linux: the prebuilt program is an AppImage, with Qt's window. It adds itself to the app menu, and a new release replaces
the file. Outside an AppImage, from source or the small command line build, none of that applies.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from heirloom.desktop.shared import Tray, choose_qt_window, host_env, run_after_quitting

__all__ = ['STARTUP_NAME', 'UPDATE_FILE', 'Tray', 'add_to_menu', 'can_update_itself', 'choose_window_engine',
           'host_env', 'open_folder', 'opens_window_by_default', 'other_heirlooms_running', 'start_at_login',
           'start_install', 'starts_at_login', 'startup_command', 'update_blocker']

UPDATE_FILE = 'heirloom_linux_x64.AppImage'
STARTUP_NAME = 'Start when you log in'
# its old copy keeps running from the file it was started from, so replacing that can't get in the way of anything.
# Copied next to it first, as the two may be on different disks and a rename needs the same one
INSTALL = '''
cp -f "$HL_SETUP" "$HL_TARGET.new" && chmod +x "$HL_TARGET.new" && mv -f "$HL_TARGET.new" "$HL_TARGET"
if [ -n "$HL_REOPEN" ]; then exec "$HL_TARGET" gui --background; fi
'''


def _appimage() -> Path | None:
    path = os.environ.get('APPIMAGE')
    return Path(path) if path else None


def _config_home() -> Path:
    return Path(os.environ.get('XDG_CONFIG_HOME') or '~/.config').expanduser()


def _data_home() -> Path:
    return Path(os.environ.get('XDG_DATA_HOME') or '~/.local/share').expanduser()


def _autostart_entry() -> Path:
    return _config_home() / 'autostart' / 'heirloom.desktop'


def _desktop_entry(appimage: Path, arguments: str = '') -> str:
    quoted = ''.join(f'\\{c}' if c in '"`$\\' else c for c in str(appimage))
    return ('[Desktop Entry]\nType=Application\nName=Heirloom\nComment=Play your Epic Games library\n'
            f'Exec="{quoted}"{arguments}\nIcon=heirloom\nCategories=Game;\nTerminal=false\n')


def _write_if_changed(path: Path, text: str) -> None:
    if not path.exists() or path.read_text(encoding='utf-8') != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def choose_window_engine() -> None:
    choose_qt_window()


def add_to_menu() -> None:
    """Puts Heirloom in the app menu, and keeps that and starting at login right if the file has moved"""
    appimage = _appimage()
    if not appimage:
        return
    try:
        _write_if_changed(_data_home() / 'applications' / 'heirloom.desktop', _desktop_entry(appimage))
        icon = _data_home() / 'icons' / 'hicolor' / '256x256' / 'apps' / 'heirloom.png'
        if not icon.exists() and (appdir := os.environ.get('APPDIR')):
            icon.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(Path(appdir) / 'heirloom.png', icon)
        if starts_at_login():
            start_at_login(True)
    except OSError:
        # the menu is a convenience, and a read-only home shouldn't stop the window
        pass


def opens_window_by_default() -> bool:
    return _appimage() is not None


def open_folder(path: str | Path) -> None:
    subprocess.Popen(['xdg-open', str(path)], env=host_env())


def startup_command() -> str | None:
    appimage = _appimage()
    return f'"{appimage}" gui --background' if appimage else None


def starts_at_login() -> bool:
    return _autostart_entry().exists()


def start_at_login(enabled: bool) -> None:
    appimage = _appimage()
    if not enabled:
        _autostart_entry().unlink(missing_ok=True)
    elif appimage:
        _write_if_changed(_autostart_entry(), _desktop_entry(appimage, ' gui --background'))
    else:
        raise ValueError('Starting at login needs Heirloom from its AppImage')


def can_update_itself() -> bool:
    appimage = _appimage()
    return appimage is not None and os.access(appimage, os.W_OK) and os.access(appimage.parent, os.W_OK)


def update_blocker() -> str:
    """Why a copy that could update itself can't, to tell the user"""
    appimage = _appimage()
    if not appimage or can_update_itself():
        return ''
    return f'Heirloom can\'t replace itself in {appimage.parent}. Move it somewhere you can write to, or download the ' \
           'new version from the sidebar.'


def other_heirlooms_running() -> bool:
    """Others can carry on while the file is replaced"""
    return False


def start_install(setup: Path) -> None:
    """Starts what replaces the AppImage once this process has ended; this process should quit next"""
    run_after_quitting(INSTALL, {'HL_SETUP': str(setup), 'HL_TARGET': str(_appimage()),
                                 # with no tray to return to, the window closing means the user is done
                                 'HL_REOPEN': '1' if Tray.available() else ''})
