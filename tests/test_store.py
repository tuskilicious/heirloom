"""The plugin store: the plugins that come with Heirloom, and installing, switching and removing plugins in the window."""
import argparse
import shutil
import sys
from datetime import datetime

import pytest

from heirloom.gui.app import STORE, GuiApi
from heirloom.models.game import InstalledGame, PlaytimeSession
from heirloom.plugins import GameExited, GameInstalled, GameLaunching, PluginManager

GAME = InstalledGame(app_name='Fish', install_path='C:/Games/Fish', title='Fish Game', version='2')


def load_store(tmp_path):
    """Every plugin of the store, enabled and loaded"""
    folder = tmp_path / 'plugins'
    shutil.copytree(STORE, folder)
    manager = PluginManager(folder)
    for name in manager.discover():
        manager.set_enabled(name, True)
    manager.load(argparse.ArgumentParser().add_subparsers())
    return manager


def test_store_plugins_load(tmp_path):
    manager = load_store(tmp_path)
    assert set(manager.discover()) == {'notifications', 'power-plan', 'close-epic-launcher'}
    assert manager.errors == {}


def test_notification_names_the_game(tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr('subprocess.run', lambda command, **options: shown.append((command, options.get('env', {}))))
    load_store(tmp_path).emit(GameInstalled('Fish', GAME))
    (command, env), = shown
    assert 'Fish Game is installed' in [*command, *env.values()], 'the title, outside any script'


@pytest.mark.skipif(sys.platform != 'win32', reason='power plans are Windows only')
def test_power_plan_switches_back_after_playing(tmp_path, monkeypatch):
    calls = []

    def powercfg(command, **options):
        calls.append(command)
        return type('Result', (), {'stdout': 'Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)',
                                   'returncode': 1})()

    monkeypatch.setattr('subprocess.run', powercfg)
    manager = load_store(tmp_path)
    manager.emit(GameLaunching('Fish', GAME, ['fish.exe'], {}, 'C:/Games/Fish'))
    manager.emit(GameExited('Fish', PlaytimeSession(datetime.now(), datetime.now(), 0)))
    plan_calls = [call[1:] for call in calls if call[0] == 'powercfg']
    assert plan_calls == [['/getactivescheme'], ['/setactive', 'SCHEME_MIN'],
                          ['/setactive', '381b4222-f694-41f0-9685-ff5bb260df2e']]


def test_install_switch_and_remove_from_the_window(lgd_home):
    api = GuiApi(None, lambda: {})
    store = {plugin['name']: plugin for plugin in api.plugins()['store']}
    assert store['notifications'] == {'name': 'notifications', 'title': 'Notifications', 'installed': False,
                                      'description': 'A desktop notification when a game finishes installing or '
                                                     'updating'}

    plugins = api.install_plugin('notifications')
    assert plugins['installed'][0] | {'description': ''} == {'name': 'notifications', 'title': 'Notifications',
                                                             'description': '', 'enabled': True}
    assert (lgd_home / 'plugins' / 'notifications' / 'main.py').is_file()
    assert [plugin['installed'] for plugin in plugins['store'] if plugin['name'] == 'notifications'] == [True]
    with pytest.raises(ValueError):
        api.install_plugin('notifications')

    assert api.set_plugin('notifications', False)['installed'][0]['enabled'] is False
    assert api.remove_plugin('notifications')['installed'] == []
    assert not (lgd_home / 'plugins' / 'notifications').exists()
    with pytest.raises(ValueError):
        api.remove_plugin('notifications')
    with pytest.raises(ValueError):
        api.open_config_folder('..')
