"""
Switches Windows to the High performance power plan while a game runs, and back to the plan before afterwards.
Switching back needs "heirloom launch" to wait for the game, which it does unless playtime tracking and cloud save
sync are both off.
"""
import re
import subprocess
import sys

# powercfg's alias for the High performance plan
HIGH_PERFORMANCE = 'SCHEME_MIN'


def powercfg(*arguments):
    return subprocess.run(['powercfg', *arguments], capture_output=True, text=True, timeout=30, check=True,
                          creationflags=subprocess.CREATE_NO_WINDOW).stdout


def setup(plugin):
    if sys.platform != 'win32':
        plugin.log.warning('Power plans are a Windows thing, this plugin does nothing here.')
        return
    previous = []

    def on_launch(event):
        try:
            active = re.search(r'[0-9a-f]{8}-[0-9a-f-]{27}', powercfg('/getactivescheme'), re.IGNORECASE)
            powercfg('/setactive', HIGH_PERFORMANCE)
        except (OSError, subprocess.SubprocessError) as e:
            # laptops with Modern Standby have no High performance plan
            plugin.log.warning(f'Could not switch to the High performance power plan: {e!r}')
            return
        if active:
            previous.append(active[0])

    def on_exit(event):
        if previous:
            try:
                powercfg('/setactive', previous.pop())
            except (OSError, subprocess.SubprocessError) as e:
                plugin.log.warning(f'Could not switch back to the power plan from before: {e!r}')

    plugin.on('game_launching', on_launch)
    plugin.on('game_exited', on_exit)
