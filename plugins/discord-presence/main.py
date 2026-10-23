"""
Discord Rich Presence: shows the game started with "heirloom launch" in your Discord status while it runs.
It talks to the Discord app on this computer over its local IPC connection, so it needs no Discord login.
"""
import json
import os
import socket
import struct
import sys
import threading
import time
import uuid
from pathlib import Path

# The Discord application whose name Discord shows as "Playing <name>": Heirloom's own, unless
# HEIRLOOM_DISCORD_CLIENT_ID names another (create one at https://discord.com/developers/applications)
CLIENT_ID = os.environ.get('HEIRLOOM_DISCORD_CLIENT_ID') or '1563096388940599468'

HANDSHAKE, FRAME, CLOSE = 0, 1, 2


def connect_to_discord():
    """A connection to the Discord app, or None when it isn't running"""
    for number in range(10):
        if sys.platform == 'win32':
            try:
                return Path(rf'\\.\pipe\discord-ipc-{number}').open('r+b', buffering=0)
            except OSError:
                continue
        for folder in _socket_folders():
            sock = socket.socket(socket.AF_UNIX)
            sock.settimeout(5)
            try:
                sock.connect(str(folder / f'discord-ipc-{number}'))
            except OSError:
                sock.close()
                continue
            connection = sock.makefile('rwb', buffering=0)
            # the connection keeps the socket open until it is closed itself
            sock.close()
            return connection
    return None


def _socket_folders():
    bases = [os.environ.get(name) for name in ('XDG_RUNTIME_DIR', 'TMPDIR', 'TMP', 'TEMP')] + ['/tmp']
    # also where the Flatpak and Snap Discord apps put theirs
    return [Path(base, app) for base in bases if base for app in ('', 'app/com.discordapp.Discord', 'snap.discord')]


def send(connection, op, payload):
    data = json.dumps(payload).encode()
    connection.write(struct.pack('<II', op, len(data)) + data)


def receive(connection):
    op, length = struct.unpack('<II', _read(connection, 8))
    return op, json.loads(_read(connection, length))


def _read(connection, size):
    data = b''
    while len(data) < size:
        chunk = connection.read(size - len(data))
        if not chunk:
            raise ConnectionError('Discord closed the connection')
        data += chunk
    return data


class Presence:
    def __init__(self, log):
        self.log = log
        self._lock = threading.Lock()
        self._connection = None
        self._hidden = False

    def show(self, title, started):
        """In the background, so a slow or missing Discord never holds up the game"""
        self._hidden = False
        threading.Thread(target=self._show, args=(title, started), daemon=True).start()

    def hide(self):
        with self._lock:
            self._hidden = True
            connection, self._connection = self._connection, None
        if connection:
            # Discord clears the activity when the connection closes
            connection.close()

    def _show(self, title, started):
        connection = connect_to_discord()
        if connection is None:
            self.log.debug('Discord is not running, not showing the game there.')
            return
        try:
            send(connection, HANDSHAKE, {'v': 1, 'client_id': CLIENT_ID})
            op, reply = receive(connection)
            if op == CLOSE:
                raise ConnectionError(f'Discord refused the connection: {reply.get("message")} ({reply.get("code")})')
            send(connection, FRAME, {'cmd': 'SET_ACTIVITY', 'nonce': str(uuid.uuid4()), 'args': {
                'pid': os.getpid(),
                'activity': {'details': title, 'timestamps': {'start': int(started)}},
            }})
            op, reply = receive(connection)
            if op == CLOSE or reply.get('evt') == 'ERROR':
                raise ConnectionError(f'Discord did not show the game: {reply}')
        except Exception as e:
            self.log.warning(f'Could not show the game in Discord: {e!r}')
            connection.close()
            return
        with self._lock:
            if self._hidden:
                # the game already exited
                connection.close()
            else:
                self._connection = connection
                self.log.debug(f'Showing "{title}" in Discord.')


def setup(plugin):
    presence = Presence(plugin.log)
    plugin.on('game_launching', lambda event: presence.show(event.game.title, time.time()))
    plugin.on('game_exited', lambda event: presence.hide())
