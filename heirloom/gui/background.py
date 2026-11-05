"""Keeping "heirloom gui" to one window at a time: a second one asks the first to show itself."""
from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger('GUI')

# what a second "heirloom gui" sends the one already running, to bring its window back
SHOW = b'show\n'


def claim_window(port_file: Path, on_show: Callable[[], None]) -> bool:
    """
    False if a window is already open, which is asked to show itself; otherwise True, and this process answers the
    next one, through a socket on localhost whose port is kept in port_file.
    """
    try:
        # an open window accepts at once; with none, Windows takes about two seconds to refuse, so it is not waited
        # for: the port file is left behind each time Heirloom quits
        with socket.create_connection(('127.0.0.1', int(port_file.read_text())), timeout=0.25) as other:
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
