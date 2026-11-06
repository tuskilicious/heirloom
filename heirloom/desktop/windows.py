"""
Windows: the window is WebView2, the tray is a .NET icon through pythonnet, and a copy from the installer updates
itself by running the installer of the new release silently.
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

assert sys.platform == 'win32'

__all__ = ['STARTUP_NAME', 'UPDATE_FILE', 'WINDOW_ICON', 'Tray', 'add_to_menu', 'can_update_itself', 'choose_window_engine',
           'game_runners', 'host_env', 'open_folder', 'opens_window_by_default', 'other_heirlooms_running', 'prepare_window', 'start_at_login',
           'start_install', 'starts_at_login', 'startup_command', 'update_blocker']

UPDATE_FILE = 'heirloom_windows_x64_setup.exe'
STARTUP_NAME = 'Start with Windows'
# the program's own, which Windows uses
WINDOW_ICON = None
# the Run key value that starts Heirloom with Windows
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'Heirloom'
# the installer upgrades the copy it finds, and keeps the choices made when it was first installed; it leaves running
# programs alone, and failing leaves the old version to reopen. Paths are given as variables, so nothing needs quoting
INSTALL = '''
Wait-Process -Id $env:HL_PID -ErrorAction SilentlyContinue
Start-Process $env:HL_SETUP -ArgumentList $env:HL_ARGUMENTS -Wait
Start-Process $env:HL_REOPEN -ArgumentList '--background'
'''


def choose_window_engine() -> None:
    """pywebview finds WebView2 by itself"""


def prepare_window(window) -> None:
    """WebView2 needs nothing more, unless tests/window_probe.py is to look at it, as Qt lets anything through a variable"""
    if port := os.environ.get('HEIRLOOM_REMOTE_DEBUGGING'):
        import webview
        webview.settings['REMOTE_DEBUGGING_PORT'] = int(port)


def add_to_menu() -> None:
    """The installer makes the Start menu shortcut"""


def opens_window_by_default() -> bool:
    return False


def game_runners() -> list[str] | None:
    """Windows runs Windows games by itself"""
    return None


def host_env() -> dict[str, str]:
    """The environment for games and other programs to start with"""
    return dict(os.environ)


def open_folder(path: str | Path) -> None:
    os.startfile(path)


def startup_command() -> str | None:
    """What Windows runs at sign-in: the windowed launcher next to heirloom.exe, hidden; None outside the installer"""
    launcher = Path(sys.executable).with_name('heirloom-gui.exe')
    if not getattr(sys, 'frozen', False) or not launcher.exists():
        return None
    return f'"{launcher}" --background'


def starts_at_login() -> bool:
    from heirloom.lfs.windows_helpers import HKEY_CURRENT_USER, query_registry_value
    return query_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE) is not None


def start_at_login(enabled: bool) -> None:
    from heirloom.lfs.windows_helpers import (
        HKEY_CURRENT_USER,
        remove_registry_value,
        set_registry_value,
    )
    command = startup_command()
    if not enabled:
        if starts_at_login():
            remove_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE)
        return
    if not command:
        raise ValueError('Starting with Windows needs Heirloom from its installer')
    set_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, command)


class Tray:
    """Heirloom's icon in the Windows notification area, with Open and Quit; it runs its own message loop"""

    def __init__(self, on_open: Callable[[], None], on_quit: Callable[[], None]):
        self._on_open, self._on_quit = on_open, on_quit
        self._icon = None

    @staticmethod
    def available() -> bool:
        try:
            import clr  # noqa: F401
            return True
        except Exception:
            return False

    def start(self) -> None:
        # Windows Forms wants a single-threaded apartment, which only a .NET thread can be given
        import clr  # noqa: F401
        from System.Threading import ApartmentState, Thread, ThreadStart
        thread = Thread(ThreadStart(self._run))
        thread.SetApartmentState(ApartmentState.STA)
        thread.IsBackground = True
        thread.Start()

    def _run(self) -> None:
        import clr
        clr.AddReference('System.Windows.Forms')
        clr.AddReference('System.Drawing')
        from System.Drawing import Icon, SystemIcons
        from System.Windows.Forms import Application, ContextMenuStrip, NotifyIcon

        icon = NotifyIcon()
        try:
            icon.Icon = Icon.ExtractAssociatedIcon(sys.executable)
        except Exception:
            icon.Icon = SystemIcons.Application
        icon.Text = 'Heirloom'
        menu = ContextMenuStrip()
        menu.Items.Add('Open Heirloom').Click += lambda *_: self._on_open()
        menu.Items.Add('Quit').Click += lambda *_: self._quit()
        icon.ContextMenuStrip = menu
        icon.DoubleClick += lambda *_: self._on_open()
        icon.Visible = True
        self._icon = icon
        Application.Run()

    def _quit(self) -> None:
        self.stop()
        self._on_quit()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.Visible = False
            self._icon.Dispose()
            self._icon = None


def can_update_itself() -> bool:
    return bool(getattr(sys, 'frozen', False)) and Path(sys.executable).with_name('unins000.exe').exists()


def update_blocker() -> str:
    """Why a copy that could update itself can't, to tell the user; the installer's copy always can"""
    return ''


def other_heirlooms_running() -> bool:
    """Whether another heirloom.exe uses the files to replace: a game started from a shortcut, or a download"""
    output = subprocess.run(['tasklist', '/fi', 'imagename eq heirloom.exe', '/fo', 'csv', '/nh'], capture_output=True,
                            text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW).stdout
    return output.lower().count('heirloom.exe') > 1


def start_install(setup: Path) -> None:
    """Starts what installs setup once this process has ended, and reopens Heirloom; this process should quit next"""
    arguments = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL', '/NOCLOSEAPPLICATIONS',
                 f'/LOG="{setup.with_suffix(".log")}"']
    # the installer would turn this back on if it was on when first installed
    if not starts_at_login():
        arguments.append('/MERGETASKS="!startup"')
    env = os.environ | {'HL_PID': str(os.getpid()), 'HL_SETUP': str(setup), 'HL_ARGUMENTS': ' '.join(arguments),
                        'HL_REOPEN': str(Path(sys.executable).with_name('heirloom-gui.exe'))}
    subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-Command', INSTALL], env=env,
                     creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_BREAKAWAY_FROM_JOB)
