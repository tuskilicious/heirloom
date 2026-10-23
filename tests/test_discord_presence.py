"""The Discord Rich Presence plugin in plugins/discord-presence, against a fake Discord app."""
import argparse
import json
import os
import shutil
import socket
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from heirloom.models.game import InstalledGame, PlaytimeSession
from heirloom.plugins import GameExited, GameLaunching, PluginManager

PLUGIN = Path(__file__).parent.parent / 'plugins' / 'discord-presence'
GAME = InstalledGame(app_name='Fish', title='Fish Game', version='1', install_path='/games/fish')


class FakeDiscord:
    """The Discord app's side of the IPC connection, recording what the plugin sends"""

    def __init__(self, refuse=False):
        self.refuse = refuse
        plugin_side, self.socket = socket.socketpair()
        self.connection = plugin_side.makefile('rwb', buffering=0)
        plugin_side.close()
        self.frames = []
        self.closed = threading.Event()
        threading.Thread(target=self._serve, daemon=True).start()

    def _receive(self):
        header = self.socket.recv(8, socket.MSG_WAITALL)
        if len(header) < 8:
            return None
        op, length = struct.unpack('<II', header)
        return op, json.loads(self.socket.recv(length, socket.MSG_WAITALL))

    def _send(self, op, payload):
        data = json.dumps(payload).encode()
        self.socket.sendall(struct.pack('<II', op, len(data)) + data)

    def _serve(self):
        while frame := self._receive():
            self.frames.append(frame)
            op, payload = frame
            if op == 0 and self.refuse:
                self._send(2, {'code': 4000, 'message': 'Invalid Client ID'})
            elif op == 0:
                self._send(1, {'cmd': 'DISPATCH', 'evt': 'READY', 'data': {'v': 1}})
            else:
                self._send(1, {'cmd': payload['cmd'], 'nonce': payload['nonce'], 'evt': None, 'data': {}})
        self.closed.set()

    def wait_for(self, count):
        deadline = time.monotonic() + 10
        while len(self.frames) < count and time.monotonic() < deadline:
            time.sleep(0.05)
        return self.frames


def load_plugin(plugins_folder):
    """Loads the plugin the way heirloom does, from a plugins folder with it enabled"""
    shutil.copytree(PLUGIN, plugins_folder / 'discord-presence', dirs_exist_ok=True)
    manager = PluginManager(plugins_folder)
    manager.set_enabled('discord-presence', True)
    manager.load(argparse.ArgumentParser().add_subparsers())
    assert not manager.errors, manager.errors
    return manager, sys.modules['heirloom_plugin_discord_presence']


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    manager, module = load_plugin(tmp_path)
    monkeypatch.setattr(module, 'CLIENT_ID', '1234')
    # never the Discord app that may be running on this machine
    monkeypatch.setattr(module, 'connect_to_discord', lambda: None)
    return manager, module


def launch(manager):
    manager.emit(GameLaunching('Fish', GAME, ['fish.exe'], {}, '/games/fish'))


def exit_game(manager):
    now = datetime.now(timezone.utc)
    manager.emit(GameExited('Fish', PlaytimeSession(start=now, end=now, exit_code=0)))


def test_shows_the_game_while_it_runs(plugin, monkeypatch):
    manager, module = plugin
    discord = FakeDiscord()
    monkeypatch.setattr(module, 'connect_to_discord', lambda: discord.connection)
    started = int(time.time())

    launch(manager)
    (handshake_op, handshake), (activity_op, activity) = discord.wait_for(2)
    assert (handshake_op, handshake) == (0, {'v': 1, 'client_id': '1234'})
    assert activity_op == 1 and activity['cmd'] == 'SET_ACTIVITY'
    assert activity['args']['pid'] == os.getpid()
    assert activity['args']['activity']['details'] == 'Fish Game'
    assert started <= activity['args']['activity']['timestamps']['start'] <= time.time()
    assert not discord.closed.is_set(), 'stays connected while the game runs'

    exit_game(manager)
    assert discord.closed.wait(5), 'the connection closes when the game exits, which clears the activity'


def test_refused_or_missing_discord_does_not_stop_the_launch(plugin, monkeypatch, caplog):
    manager, module = plugin
    refusing = FakeDiscord(refuse=True)
    monkeypatch.setattr(module, 'connect_to_discord', lambda: refusing.connection)
    launch(manager)
    assert refusing.closed.wait(5)
    assert len(refusing.frames) == 1, 'no activity after the handshake was refused'
    assert 'Invalid Client ID (4000)' in caplog.text

    monkeypatch.setattr(module, 'connect_to_discord', lambda: None)
    caplog.clear()
    launch(manager)
    exit_game(manager)
    time.sleep(0.2)
    assert not [record for record in caplog.records if record.levelname in ('WARNING', 'ERROR')]


def test_uses_heirlooms_discord_application_unless_told_otherwise(tmp_path, monkeypatch):
    monkeypatch.delenv('HEIRLOOM_DISCORD_CLIENT_ID', raising=False)
    assert load_plugin(tmp_path)[1].CLIENT_ID == '1563096388940599468'
    monkeypatch.setenv('HEIRLOOM_DISCORD_CLIENT_ID', '42')
    assert load_plugin(tmp_path)[1].CLIENT_ID == '42'
