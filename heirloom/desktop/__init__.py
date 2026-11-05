"""
What differs between Windows, Linux and Mac for a program on the desktop. Each has a module of its own with the same
names, listed in its __all__, and only this system's is imported. Use them as desktop.open_folder(...).
"""
import sys

if sys.platform == 'win32':
    from heirloom.desktop.windows import *  # noqa: F403
elif sys.platform == 'darwin':
    from heirloom.desktop.macos import *  # noqa: F403
else:
    from heirloom.desktop.linux import *  # noqa: F403
