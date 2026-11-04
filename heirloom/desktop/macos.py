"""
Mac: the prebuilt program is Heirloom.app with Qt's window, and a new release replaces the app from the release's disk
image. It isn't signed by a paid Apple account, so macOS asks once; a file Heirloom downloads itself isn't marked as
downloaded, so updating doesn't ask again.
"""
from __future__ import annotations

import os
import platform
import plistlib
import subprocess
import sys
from pathlib import Path

from heirloom.desktop.shared import Tray, choose_qt_window, host_env, run_after_quitting

__all__ = ['STARTUP_NAME', 'UPDATE_FILE', 'Tray', 'add_to_menu', 'can_update_itself', 'choose_window_engine',
           'host_env', 'open_folder', 'opens_window_by_default', 'other_heirlooms_running', 'start_at_login',
           'start_install', 'starts_at_login', 'startup_command', 'update_blocker']

UPDATE_FILE = f'heirloom_macos_{"arm64" if platform.machine() == "arm64" else "x64"}.dmg'
STARTUP_NAME = 'Start when you log in'
LAUNCH_AGENT = 'io.github.tuskilicious.heirloom'
# the old app is moved aside only once the new one is complete, and put back if that fails
INSTALL = '''
disk=$(mktemp -d)
if hdiutil attach "$HL_SETUP" -nobrowse -readonly -mountpoint "$disk" >/dev/null; then
    rm -rf "$HL_TARGET.new" "$HL_TARGET.old"
    if ditto "$disk/Heirloom.app" "$HL_TARGET.new" && mv "$HL_TARGET" "$HL_TARGET.old"; then
        mv "$HL_TARGET.new" "$HL_TARGET" || mv "$HL_TARGET.old" "$HL_TARGET"
        rm -rf "$HL_TARGET.old"
    fi
    hdiutil detach "$disk" -quiet
fi
rm -rf "$HL_TARGET.new"
if [ -n "$HL_REOPEN" ]; then open "$HL_TARGET" --args gui --background; fi
'''


def _app() -> Path | None:
    """Heirloom.app, if this is running from one: its program is in Contents/MacOS"""
    if not getattr(sys, 'frozen', False):
        return None
    app = Path(sys.executable).parents[2]
    return app if app.suffix == '.app' else None


def _translocated(app: Path) -> bool:
    """macOS runs an app it has just warned about from a temporary read-only copy, until it's moved out of Downloads"""
    return 'AppTranslocation' in app.parts


def _launch_agent() -> Path:
    return Path.home() / 'Library' / 'LaunchAgents' / f'{LAUNCH_AGENT}.plist'


def choose_window_engine() -> None:
    choose_qt_window()


def add_to_menu() -> None:
    """A Mac finds apps by themselves"""


def opens_window_by_default() -> bool:
    return _app() is not None


def open_folder(path: str | Path) -> None:
    subprocess.Popen(['open', str(path)], env=host_env())


def startup_command() -> str | None:
    return f'"{sys.executable}" gui --background' if _app() else None


def starts_at_login() -> bool:
    return _launch_agent().exists()


def start_at_login(enabled: bool) -> None:
    if not enabled:
        _launch_agent().unlink(missing_ok=True)
    elif _app():
        _launch_agent().parent.mkdir(parents=True, exist_ok=True)
        _launch_agent().write_bytes(plistlib.dumps({'Label': LAUNCH_AGENT, 'RunAtLoad': True,
                                                    'ProgramArguments': [sys.executable, 'gui', '--background']}))
    else:
        raise ValueError('Starting at login needs Heirloom.app')


def can_update_itself() -> bool:
    app = _app()
    return app is not None and not _translocated(app) and os.access(app.parent, os.W_OK)


def update_blocker() -> str:
    """Why a copy that could update itself can't, to tell the user"""
    if not _app() or can_update_itself():
        return ''
    return 'Move Heirloom to your Applications folder so it can update itself.'


def other_heirlooms_running() -> bool:
    """Others can carry on while the app is replaced"""
    return False


def start_install(setup: Path) -> None:
    """Starts what replaces the app once this process has ended; this process should quit next"""
    run_after_quitting(INSTALL, {'HL_SETUP': str(setup), 'HL_TARGET': str(_app()),
                                 'HL_REOPEN': '1' if Tray.available() else ''})
