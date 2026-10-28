"""
heirloom-gui.exe, what the Start menu and desktop shortcuts run. It is a windowed program, so opening it shows no
terminal, and it starts "heirloom.exe gui" next to it in a console that has no window either. The window needs a
console: the downloads it starts share it, so Stop can interrupt them with Ctrl+Break.
"""
import subprocess
import sys
from pathlib import Path

subprocess.Popen([str(Path(sys.executable).with_name('heirloom.exe')), 'gui', *sys.argv[1:]],
                 creationflags=subprocess.CREATE_NO_WINDOW)
