# PyInstaller's folder build. On Windows, for the installer: heirloom.exe, the command line program, and
# heirloom-gui.exe, which the shortcuts run to open the window without a terminal (see heirloom_gui.py); both share one
# _internal. On Linux, what goes in the AppImage (see build_appimage.sh). On Mac, Heirloom.app.
#   pyinstaller --distpath installer/build installer/heirloom.spec
import os
import sys

root = os.path.dirname(SPECPATH)
icon = os.path.join(root, 'assets', 'windows_icon.ico')
datas = [(os.path.join(root, 'heirloom', 'gui', 'web'), 'heirloom/gui/web')]
excludes = []

if sys.platform != 'win32':
    # the tray's icon, which on Linux the app menu uses too
    datas.append((icon, 'heirloom/desktop'))
    # QtPy mentions every part of Qt, and PyInstaller would take them all
    import PySide6
    qt_modules = {'QtCore', 'QtGui', 'QtNetwork', 'QtPrintSupport', 'QtWebChannel', 'QtWebEngineCore',
                  'QtWebEngineWidgets', 'QtWidgets'}
    excludes = [f'PySide6.{name}' for name in {file.split('.')[0] for file in os.listdir(os.path.dirname(PySide6.__file__))
                                               if file.startswith('Qt')} - qt_modules]


# On Linux, libraries that have to come from the system the program runs on, to match its graphics drivers, fonts and
# sound (AppImage's own list of them), and what only Qt's plugins for GTK themes and for printing brought along
SYSTEM_LIBRARIES = {
    'libasound', 'libcom_err', 'libdrm', 'libEGL', 'libexpat', 'libfontconfig', 'libfreetype', 'libgbm', 'libgcc_s',
    'libgio-2.0', 'libGL', 'libGLdispatch', 'libGLX', 'libglapi', 'libglib-2.0', 'libgmodule-2.0', 'libgobject-2.0',
    'libgpg-error', 'libgthread-2.0', 'libharfbuzz', 'libICE', 'libOpenGL', 'libp11-kit', 'libSM', 'libstdc++',
    'libusb-1.0', 'libuuid', 'libX11', 'libxcb', 'libz',
    'libatk-1.0', 'libatk-bridge-2.0', 'libatspi', 'libavahi-client', 'libavahi-common', 'libcairo', 'libcairo-gobject',
    'libcups', 'libdatrie', 'libepoxy', 'libfribidi', 'libgdk-3', 'libgdk_pixbuf-2.0', 'libgmp', 'libgnutls',
    'libgraphite2', 'libgtk-3', 'libhogweed', 'libidn2', 'libnettle', 'libpango-1.0', 'libpangocairo-1.0',
    'libpangoft2-1.0', 'libpixman-1', 'libtasn1', 'libthai', 'libunistring',
}


def needed(entry):
    """Without the parts of Qt the window doesn't use, and on Linux what comes from the system"""
    path = entry[0].replace(os.sep, '/')
    if sys.platform == 'linux' and os.path.basename(path).split('.so')[0] in SYSTEM_LIBRARIES:
        return False
    if '/qtwebengine_locales/' in path:
        return 'en-US' in path
    return not any(part in path for part in ('PySide6/Qt/qml/', 'PySide6/Qt/translations/', 'plugins/qmltooling/',
                                             'plugins/platformthemes/libqgtk3', 'plugins/position/',
                                             'plugins/printsupport/', 'plugins/egldeviceintegrations/'))


cli = Analysis([os.path.join(root, 'heirloom', 'cli.py')], datas=datas, excludes=excludes)
if sys.platform != 'win32':
    cli.datas = [entry for entry in cli.datas if needed(entry)]
    cli.binaries = [entry for entry in cli.binaries if needed(entry)]
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
