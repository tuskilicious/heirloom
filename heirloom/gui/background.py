"""
Keeping "heirloom gui" running in the background: one window at a time, an icon in the Windows tray, and starting
with Windows. The window hides to the tray when closed, so downloads and updates go on.
"""
from __future__ import annotations

import logging
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

if sys.platform == 'win32':
    from heirloom.lfs.windows_helpers import (
        HKEY_CURRENT_USER,
        query_registry_value,
        remove_registry_value,
        set_registry_value,
    )

log = logging.getLogger('GUI')

# what a second "heirloom gui" sends the one already running, to bring its window back
SHOW = b'show\n'
# the Run key value that starts Heirloom with Windows
RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
RUN_VALUE = 'Heirloom'


def claim_window(port_file: Path, on_show: Callable[[], None]) -> bool:
    """
    False if a window is already open, which is asked to show itself; otherwise True, and this process answers the
    next one, through a socket on localhost whose port is kept in port_file.
    """
    try:
        with socket.create_connection(('127.0.0.1', int(port_file.read_text())), timeout=2) as other:
            other.sendall(SHOW)
            return False
    except (OSError, ValueError):
        pass
    server = socket.create_server(('127.0.0.1', 0))
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(server.getsockname()[1]))

    def answer() -> None:
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                try:
                    if connection.recv(len(SHOW)) == SHOW:
                        on_show()
                except OSError:
                    continue

    threading.Thread(target=answer, daemon=True).start()
    return True


def startup_command() -> str | None:
    """What Windows runs at sign-in: the windowed launcher next to heirloom.exe, hidden; None outside the installer"""
    launcher = Path(sys.executable).with_name('heirloom-gui.exe')
    if sys.platform != 'win32' or not getattr(sys, 'frozen', False) or not launcher.exists():
        return None
    return f'"{launcher}" --background'


def starts_with_windows() -> bool:
    if sys.platform == 'win32':
        return query_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE) is not None
    return False


def start_with_windows(enabled: bool) -> None:
    command = startup_command()
    if sys.platform == 'win32':
        if not enabled:
            if starts_with_windows():
                remove_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE)
            return
        if command:
            set_registry_value(HKEY_CURRENT_USER, RUN_KEY, RUN_VALUE, command)
            return
    if enabled:
        raise ValueError('Starting with Windows needs Heirloom from its installer, on Windows')


class Tray:
    """Heirloom's icon in the Windows notification area, with Open and Quit; it runs its own message loop"""

    def __init__(self, on_open: Callable[[], None], on_quit: Callable[[], None]):
        self._on_open, self._on_quit = on_open, on_quit
        self._icon = None

    @staticmethod
    def available() -> bool:
        if sys.platform != 'win32':
            return False
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
