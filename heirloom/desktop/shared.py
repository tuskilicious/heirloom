"""What Linux and Mac have in common: Qt's window and tray, and keeping the bundled files away from other programs."""
from __future__ import annotations

import functools
import importlib.util
import os
import subprocess
import sys
import threading
from collections.abc import Callable, Mapping
from pathlib import Path

ICON = Path(__file__).with_name('windows_icon.ico')
# runs after this process has ended, so a failure leaves the old version in place, to reopen if it should
WAIT_FOR_HEIRLOOM = 'while kill -0 "$HL_PID" 2>/dev/null; do sleep 1; done\n'


def has_qt() -> bool:
    return importlib.util.find_spec('PySide6') is not None


def choose_qt_window() -> None:
    """The prebuilt programs have Qt's window; an install from source may have GTK's, which pywebview finds by itself"""
    if has_qt():
        os.environ.setdefault('PYWEBVIEW_GUI', 'qt')


def host_env() -> dict[str, str]:
    """
    The environment for games and other programs to start with. PyInstaller and Qt point variables at the bundled
    files, and Wine or a file manager would load the wrong libraries from there. PyInstaller keeps the original.
    """
    bundle = getattr(sys, '_MEIPASS', None)
    if not bundle:
        return dict(os.environ)
    env = {name: value for name, value in os.environ.items() if bundle not in value}
    for name in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH'):
        if (original := env.pop(f'{name}_ORIG', None)) is not None:
            env[name] = original
    return env


def run_after_quitting(script: str, env: Mapping[str, str]) -> None:
    """Starts a shell script that outlives this process, waiting for it first"""
    subprocess.Popen(['sh', '-c', WAIT_FOR_HEIRLOOM + script], env={**host_env(), 'HL_PID': str(os.getpid()), **env},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def qt_app():
    """The application, which pywebview uses too. WebEngine has to be imported before there is one"""
    from PySide6 import QtWebEngineCore  # noqa: F401
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@functools.cache
def _tray_available() -> bool:
    try:
        qt_app()
        from PySide6.QtWidgets import QSystemTrayIcon
    except ImportError:
        # no Qt, or a system without the graphics libraries Qt uses from it; opening the window says what's wrong
        return False
    return QSystemTrayIcon.isSystemTrayAvailable()


class Tray:
    """Heirloom's icon in the system tray, or the menu bar on a Mac, with Open and Quit. GNOME may have no tray at all"""

    def __init__(self, on_open: Callable[[], None], on_quit: Callable[[], None]):
        self._on_open, self._on_quit = on_open, on_quit

    @staticmethod
    def available() -> bool:
        return _tray_available()

    def start(self) -> None:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QMenu, QSystemTrayIcon

        # what the window does for these waits for Qt's thread, which is this one
        def later(action: Callable[[], None]) -> Callable[..., None]:
            return lambda *_: threading.Thread(target=action, daemon=True).start()

        self._menu = QMenu()
        self._menu.addAction('Open Heirloom').triggered.connect(later(self._on_open))
        self._menu.addAction('Quit').triggered.connect(later(self._on_quit))
        self._icon = QSystemTrayIcon(QIcon(str(ICON)), qt_app())
        self._icon.setToolTip('Heirloom')
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(
            lambda reason: reason == QSystemTrayIcon.ActivationReason.Trigger and later(self._on_open)())
        self._icon.show()

    def stop(self) -> None:
        """The icon goes with the process, and Qt's objects can't be touched from the thread this is called on"""
