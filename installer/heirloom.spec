# PyInstaller's folder build. On Windows, for the installer: heirloom.exe, the command line program, and
# heirloom-gui.exe, which the shortcuts run to open the window without a terminal (see heirloom_gui.py); both share one
# _internal. On Linux, what goes in the AppImage (see build_appimage.sh). On Mac, Heirloom.app.
#   pyinstaller --distpath installer/build installer/heirloom.spec
import os
import sys

root = os.path.dirname(SPECPATH)
icon = os.path.join(root, 'assets', 'windows_icon.ico')

cli = Analysis([os.path.join(root, 'heirloom', 'cli.py')],
               datas=[(os.path.join(root, 'heirloom', 'gui', 'web'), 'heirloom/gui/web')])
cli_exe = EXE(PYZ(cli.pure), cli.scripts, [], exclude_binaries=True, name='heirloom', icon=icon, console=True)

if sys.platform == 'win32':
    launcher = Analysis([os.path.join(SPECPATH, 'heirloom_gui.py')])
    launcher_exe = EXE(PYZ(launcher.pure), launcher.scripts, [], exclude_binaries=True, name='heirloom-gui', icon=icon,
                       console=False)
    COLLECT(cli_exe, cli.binaries, cli.datas, launcher_exe, launcher.binaries, launcher.datas, name='heirloom')
else:
    folder = COLLECT(cli_exe, cli.binaries, cli.datas, name='heirloom')
    if sys.platform == 'darwin':
        BUNDLE(folder, name='Heirloom.app', icon=icon, bundle_identifier='io.github.tuskilicious.heirloom',
               info_plist={'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True,
                           'LSApplicationCategoryType': 'public.app-category.games'})
