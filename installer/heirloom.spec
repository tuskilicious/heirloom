# PyInstaller's folder build for the Windows installer: heirloom.exe, the command line program, and heirloom-gui.exe,
# which the shortcuts run to open the window without a terminal (see heirloom_gui.py). Both share one _internal.
#   pyinstaller --distpath installer/build installer/heirloom.spec
import os

root = os.path.dirname(SPECPATH)
icon = os.path.join(root, 'assets', 'windows_icon.ico')

cli = Analysis([os.path.join(root, 'heirloom', 'cli.py')],
               datas=[(os.path.join(root, 'heirloom', 'gui', 'web'), 'heirloom/gui/web')])
launcher = Analysis([os.path.join(SPECPATH, 'heirloom_gui.py')])

cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name='heirloom', icon=icon, console=True)
launcher_exe = EXE(PYZ(launcher.pure), launcher.scripts, [], exclude_binaries=True, name='heirloom-gui', icon=icon,
                   console=False)
COLLECT(cli_exe, cli.binaries, cli.datas, launcher_exe, launcher.binaries, launcher.datas, name='heirloom')
