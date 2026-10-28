"""Closes the Epic Games Launcher when a game starts, so it doesn't run in the background while you play"""
import subprocess
import sys


def setup(plugin):
    if sys.platform != 'win32':
        plugin.log.warning('This plugin closes the Windows Epic Games Launcher, it does nothing here.')
        return

    def on_launch(event):
        # asks it to close, as its window's X would, rather than ending it
        result = subprocess.run(['taskkill', '/IM', 'EpicGamesLauncher.exe'], capture_output=True, text=True,
                                timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            plugin.log.info('Closed the Epic Games Launcher.')

    plugin.on('game_launching', on_launch)
