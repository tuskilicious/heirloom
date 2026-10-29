"""
"heirloom gui": a window over the game library. The page in web/ is shown by pywebview and calls GuiApi;
themes add their own CSS to it. Each action runs as its own "heirloom" process, as the download queue's jobs
do, so playtime, plugins and resumable downloads work just as they do in the terminal.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from heirloom.downloader.queue import heirloom_command, start_job, stop_job
from heirloom.gui.background import (
    Tray,
    claim_window,
    start_with_windows,
    starts_with_windows,
    startup_command,
)
from heirloom.lfs.eos import (
    add_registry_entries,
    query_registry_entries,
    remove_registry_entries,
)
from heirloom.lfs.lgndry import LGDLFS
from heirloom.models.game import Game
from heirloom.plugins import PluginManager
from heirloom.themes import Theme

log = logging.getLogger('GUI')

WEB = Path(__file__).parent / 'web'
# plugins that come with Heirloom, to install from the window
STORE = Path(__file__).parent.parent / 'store'
# the window's own look, Keeper Light, in web/style.css
WINDOW_THEME = 'heirloom'
# how the window shows the library, kept between runs in window.json: the first of each is the default
VIEW_CHOICES = {'filter': ('all', 'installed', 'updates'), 'sort': ('title', 'recent', 'played', 'size')}
# portrait art first, as the library shows covers
COVER_TYPES = ('DieselGameBoxTall', 'OfferImageTall', 'DieselStoreFrontTall', 'Thumbnail', 'DieselGameBox')
# landscape art for the banner of the game played last
ART_TYPES = ('DieselGameBox', 'DieselStoreFrontWide', 'OfferImageWide')

# downloads (and uninstalls and repairs) run one at a time, as heirloom installs only one game at a time
DOWNLOADS = ('install', 'uninstall', 'repair', 'overlay')
COMMANDS = {
    'install': ['-y', 'install'],
    'uninstall': ['-y', 'uninstall'],
    'repair': ['-y', 'repair'],
    'sync': ['-y', 'sync-saves'],
    # the Epic overlay: installing also turns it on, and installing again updates it
    'overlay': ['-y', 'eos-overlay', 'install'],
    'overlay_remove': ['-y', 'eos-overlay', 'remove'],
    'play': ['-y', 'launch'],
    'login': ['auth'],
}

PROGRESS = re.compile(r'= Progress: (\d+(?:\.\d+)?)%')
SPEED = re.compile(r'\+ Download\s+- ([\d.]+ MiB/s) \(raw\)')
LOG_LINE = re.compile(r'^\[[\w.-]+\] [A-Z]+: (.*)$')

# writes a desktop shortcut from HL_* variables, so no text from Epic is ever part of the script
SHORTCUT = '''
$shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut(
    (Join-Path ([Environment]::GetFolderPath('Desktop')) "$env:HL_NAME.lnk"))
$shortcut.TargetPath = $env:HL_TARGET
$shortcut.Arguments = $env:HL_ARGUMENTS
$shortcut.IconLocation = $env:HL_ICON
$shortcut.WindowStyle = 7
$shortcut.Save()
'''


def logged_in_user(lgd: LGDLFS) -> str | None:
    """The account name, if there is a login to use (user.json alone may only hold the name, see credentials.py)"""
    userdata = lgd.userdata or {}
    return userdata.get('displayName') if 'refresh_token' in userdata else None


def image_url(game: Game | None, kinds: tuple[str, ...]) -> str:
    images = {image.get('type'): image.get('url') for image in game.metadata.get('keyImages', [])} if game else {}
    return next((images[kind] for kind in kinds if images.get(kind)), '')


def open_in_file_manager(path: str | Path) -> None:
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])


def window_themes(themes: dict[str, Theme], themes_dir: Path) -> dict[str, tuple[str, str]]:
    """
    The window's themes by name, as (title, CSS): its own look, the ones that come with Heirloom (web/themes), then
    the themes with "gui_css", then any other CSS file in the themes folder, which is a theme for the window alone
    """
    found = {WINDOW_THEME: ('Heirloom', '')}
    found |= {path.stem: (_title(path), path.read_text(encoding='utf-8')) for path in sorted((WEB / 'themes').glob('*.css'))}
    found |= {theme.name: (theme.common_name, theme.css) for theme in themes.values()
              if theme.css and theme.name not in found}
    for path in sorted(themes_dir.glob('*.css')):
        css = path.read_text(encoding='utf-8', errors='replace')
        # the CSS of a theme above, under its own name or another
        if path.stem in found or any(css == known for _, known in found.values()):
            continue
        found[path.stem] = (_title(path), css)
    return found


def _title(css_file: Path) -> str:
    return css_file.stem.replace('-', ' ').replace('_', ' ').capitalize()


def read_library(lgd: LGDLFS) -> list[dict[str, Any]]:
    """The games heirloom knows about from its cached files, without going online"""
    installed = {game.app_name: game for game in lgd.get_installed_list()}
    latest = {(platform, asset.app_name): asset.build_version
              for platform, assets in (lgd.assets or {}).items() for asset in assets}
    playtime = lgd.get_playtime()
    games = []
    for app_name in set(lgd.get_game_app_names()) | set(installed):
        game, igame = lgd.get_game_meta(app_name), installed.get(app_name)
        if game and game.is_dlc:
            continue
        version = latest.get((igame.platform if igame else 'Windows', app_name))
        sessions = playtime.get(app_name, [])
        games.append({
            'app_name': app_name,
            'title': game.app_title if game else igame.title if igame else app_name,
            'cover': image_url(game, COVER_TYPES),
            'art': image_url(game, ART_TYPES),
            'installed': igame is not None,
            'version': igame.version if igame else version,
            'update': bool(igame and version and version != igame.version),
            'size': igame.install_size if igame else None,
            'store': game.third_party_store if game else None,
            'cloud_saves': bool(game and game.supports_cloud_saves),
            # seconds played, and when the last session ended
            'played': round(sum(session.duration.total_seconds() for session in sessions)),
            'last_played': max(session.end for session in sessions).isoformat() if sessions else None,
        })
    return sorted(games, key=lambda game: game['title'].lower())


@dataclass
class Job:
    id: int
    kind: str
    app_name: str
    title: str
    # queued, running, done, failed or stopped
    status: str = 'queued'
    progress: float | None = None
    speed: str = ''
    message: str = ''


class Jobs:
    """The heirloom commands the window started, each its own process"""

    def __init__(self, command: Callable[[Job], list[str]], finished: Callable[[Job], None]):
        self._command = command
        self._finished = finished
        self._lock = threading.Lock()
        self._jobs: list[Job] = []
        self._processes: dict[int, subprocess.Popen] = {}
        self._stopped: set[int] = set()

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(job) for job in self._jobs]

    def add(self, kind: str, app_name: str, title: str) -> None:
        with self._lock:
            self._jobs.append(Job(len(self._jobs) + 1, kind, app_name, title))
        self._start_next()

    def stop(self, job_id: int) -> None:
        with self._lock:
            job = next(job for job in self._jobs if job.id == job_id)
            self._stopped.add(job_id)
            process = self._processes.get(job_id)
            if job.status == 'queued':
                job.status = 'stopped'
        if process:
            threading.Thread(target=stop_job, args=(process,), daemon=True).start()

    def stop_downloads(self) -> None:
        """Stops running downloads cleanly, so they continue where they stopped next time"""
        with self._lock:
            running = [(job.id, self._processes[job.id]) for job in self._jobs
                       if job.kind in DOWNLOADS and job.id in self._processes]
            self._stopped.update(job_id for job_id, _ in running)
        for _, process in running:
            stop_job(process)

    def _start_next(self) -> None:
        with self._lock:
            downloading = any(job.status == 'running' and job.kind in DOWNLOADS for job in self._jobs)
            starting = []
            for job in self._jobs:
                if job.status != 'queued' or (job.kind in DOWNLOADS and downloading):
                    continue
                downloading = downloading or job.kind in DOWNLOADS
                job.status = 'running'
                starting.append(job)
        for job in starting:
            self._run(job)

    def _run(self, job: Job) -> None:
        try:
            process = start_job(self._command(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding='utf-8', errors='replace', env=os.environ | {'PYTHONIOENCODING': 'utf-8'})
        except OSError as e:
            with self._lock:
                job.status, job.message = 'failed', f'Could not start heirloom: {e!r}'
            return
        with self._lock:
            self._processes[job.id] = process
        threading.Thread(target=self._follow, args=(job, process), daemon=True).start()

    def _follow(self, job: Job, process: subprocess.Popen) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            with self._lock:
                self._read(job, line.rstrip())
        exit_code = process.wait()
        with self._lock:
            del self._processes[job.id]
            job.status = 'stopped' if job.id in self._stopped else 'done' if exit_code == 0 else 'failed'
        self._finished(job)
        self._start_next()

    @staticmethod
    def _read(job: Job, line: str) -> None:
        if match := PROGRESS.search(line):
            job.progress = float(match[1])
        elif match := SPEED.search(line):
            job.speed = match[1]
        else:
            text = match[1] if (match := LOG_LINE.match(line)) else line
            # skip the download statistics and traceback lines, keep what a person would read
            if text and not text.startswith((' ', '- ', '+ ')):
                job.message = text


class GuiApi:
    """
    What the page can call, as pywebview.api.<method>(). Everything else is private: pywebview walks the public
    attributes of this object (see MockLauncher in utils/webview_login.py).
    """

    def __init__(self, config_file: str | None, load_themes: Callable[[], dict[str, Theme]],
                 command: Callable[[], list[str]] = heirloom_command):
        self._config_file = config_file
        self._load_themes = load_themes
        self._heirloom = command
        self._lock = threading.Lock()
        self._games: list[dict[str, Any]] = []
        self._user: str | None = None
        self._refreshing = False
        self._notice = ''
        # a newer Heirloom release: version, name and url
        self._update: dict[str, str] | None = None
        self._jobs = Jobs(self._command, self._job_finished)
        self._read_library()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return {'user': self._user, 'refreshing': self._refreshing, 'notice': self._notice,
                    'update': self._update, 'games': self._games, 'jobs': self._jobs.snapshot()}

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def play(self, app_name: str) -> None:
        self._jobs.add('play', app_name, self._title(app_name))

    def install(self, app_name: str) -> None:
        self._jobs.add('install', app_name, self._title(app_name))

    def uninstall(self, app_name: str) -> None:
        self._jobs.add('uninstall', app_name, self._title(app_name))

    def repair(self, app_name: str) -> None:
        self._jobs.add('repair', app_name, self._title(app_name))

    def sync_saves(self, app_name: str) -> None:
        self._jobs.add('sync', app_name, self._title(app_name))

    def open_folder(self, app_name: str) -> None:
        igame = self._lgd().get_installed_game(app_name)
        if not igame or not Path(igame.install_path).is_dir():
            notice = f'The folder of {self._title(app_name)} is gone. Repair it, or uninstall it.'
            with self._lock:
                self._notice = notice
            return
        open_in_file_manager(igame.install_path)

    def open_config_folder(self, name: str) -> None:
        """Opens the themes or plugins folder, made if there is none yet, to add or remove them"""
        if name not in ('themes', 'plugins'):
            raise ValueError(f'No folder named "{name}"')
        folder = self._lgd().path / name
        folder.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(folder)

    def plugins(self) -> dict[str, Any]:
        """The plugins in the plugins folder, and the ones of the store"""
        manager = PluginManager(self._lgd().path / 'plugins')
        found, enabled = manager.discover(), manager.enabled()
        return {
            'installed': [{'name': name, 'title': manifest.common_name, 'description': manifest.description,
                           'enabled': name in enabled} for name, (_, manifest) in found.items()],
            'store': [{'name': name, 'title': manifest.common_name, 'description': manifest.description,
                       'installed': name in found} for name, (_, manifest) in PluginManager(STORE).discover().items()],
        }

    def set_plugin(self, name: str, enabled: bool) -> dict[str, Any]:
        """Turns a plugin on or off for the heirloom commands started from now on, the window's jobs included"""
        manager = PluginManager(self._lgd().path / 'plugins')
        if name not in manager.discover():
            raise ValueError(f'No plugin named "{name}"')
        manager.set_enabled(name, enabled)
        return self.plugins()

    def install_plugin(self, name: str) -> dict[str, Any]:
        """Copies a plugin of the store into the plugins folder and turns it on"""
        source = PluginManager(STORE).discover().get(name)
        manager = PluginManager(self._lgd().path / 'plugins')
        if not source or name in manager.discover():
            raise ValueError(f'No plugin named "{name}" to install')
        shutil.copytree(source[0], manager.folder / source[0].name, ignore=shutil.ignore_patterns('__pycache__'))
        manager.set_enabled(name, True)
        return self.plugins()

    def remove_plugin(self, name: str) -> dict[str, Any]:
        """Turns a plugin off and deletes its folder"""
        manager = PluginManager(self._lgd().path / 'plugins')
        if not (found := manager.discover().get(name)):
            raise ValueError(f'No plugin named "{name}"')
        manager.set_enabled(name, False)
        shutil.rmtree(found[0])
        return self.plugins()

    def create_shortcut(self, app_name: str) -> None:
        """A desktop shortcut that plays the game, with its icon; the terminal it runs in starts minimized"""
        title = self._title(app_name)
        igame = self._lgd().get_installed_game(app_name)
        if sys.platform != 'win32' or not igame:
            notice = 'Desktop shortcuts can only be made on Windows, for installed games.'
        else:
            target, *arguments = self._heirloom()
            config = ['-c', self._config_file] if self._config_file else []
            game_exe = Path(igame.install_path, igame.executable)
            # what Windows allows in a file name
            name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', title).strip(' .') or app_name
            try:
                subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', SHORTCUT],
                               env=os.environ | {
                                   'HL_NAME': name, 'HL_TARGET': target,
                                   'HL_ARGUMENTS': subprocess.list2cmdline([*arguments, *config, '-y', 'launch', app_name]),
                                   'HL_ICON': str(game_exe) if game_exe.is_file() else target,
                               },
                               creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, check=True, timeout=30)
                notice = f'Added "{name}" to your desktop.'
            except (OSError, subprocess.SubprocessError) as e:
                log.warning(f'Could not create the shortcut: {e!r}')
                notice = f'Could not add a desktop shortcut for {title}.'
        with self._lock:
            self._notice = notice

    def background(self) -> dict[str, Any]:
        """Whether Heirloom keeps going in the tray, and whether it starts with Windows (only from the installer)"""
        return {'tray': Tray.available(), 'startup_possible': startup_command() is not None,
                'starts_with_windows': starts_with_windows()}

    def set_starts_with_windows(self, enabled: bool) -> dict[str, Any]:
        start_with_windows(enabled)
        return self.background()

    def overlay(self) -> dict[str, Any] | None:
        """
        The Epic overlay, which games using Epic Online Services show friends, invites and achievements in: whether
        Heirloom installed it, and whether it is on. None off Windows, where it needs a Wine prefix (see the CLI).
        """
        if sys.platform != 'win32':
            return None
        install = self._lgd().get_overlay_install_info()
        path = query_registry_entries()['overlay_path']
        return {'installed': install is not None, 'version': install.version if install else '',
                # it may be on from the Epic Games Launcher's own copy
                'enabled': bool(path) and Path(path, 'EOSOVH-Win64-Shipping.dll').exists()}

    def set_overlay(self, enabled: bool) -> dict[str, Any] | None:
        """Turns the overlay on or off for every game, in the registry of the current user"""
        install = self._lgd().get_overlay_install_info()
        if enabled and not install:
            raise ValueError('The overlay is not installed')
        remove_registry_entries()
        if enabled and install:
            add_registry_entries(os.path.normpath(install.install_path))
        return self.overlay()

    def install_overlay(self) -> None:
        self._jobs.add('overlay', '', 'Epic overlay')

    def remove_overlay(self) -> None:
        self._jobs.add('overlay_remove', '', 'Epic overlay')

    def login(self) -> None:
        self._jobs.add('login', '', 'Epic Games account')

    def stop(self, job_id: int) -> None:
        self._jobs.stop(job_id)

    def view(self) -> dict[str, Any]:
        """How the window was left: the shelf, the sort order, and whether the sidebar was collapsed"""
        try:
            saved = json.loads((self._lgd().path / 'window.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        view: dict[str, Any] = {key: saved.get(key) if saved.get(key) in choices else choices[0]
                                for key, choices in VIEW_CHOICES.items()}
        view['rail_collapsed'] = saved.get('rail_collapsed') is True
        return view

    def set_view(self, view: dict[str, Any]) -> None:
        """Keeps how the window shows the library for the next time; anything unknown is left out"""
        kept = self.view()
        kept |= {key: view[key] for key, choices in VIEW_CHOICES.items() if view.get(key) in choices}
        if isinstance(view.get('rail_collapsed'), bool):
            kept['rail_collapsed'] = view['rail_collapsed']
        path = self._lgd().path
        path.mkdir(parents=True, exist_ok=True)
        (path / 'window.json').write_text(json.dumps(kept, indent=2), encoding='utf-8')

    def themes(self) -> dict[str, Any]:
        lgd = self._lgd()
        themes = window_themes(self._load_themes(), lgd.path / 'themes')
        name = lgd.config.get('Heirloom', 'window_theme', fallback=WINDOW_THEME)
        active = name if name in themes else WINDOW_THEME
        return {'active': active, 'css': themes[active][1],
                'themes': [{'name': name, 'title': title} for name, (title, _) in themes.items()]}

    def use_theme(self, name: str) -> dict[str, Any]:
        # a fresh read of the config, so changes heirloom made to it meanwhile are kept
        lgd = self._lgd()
        if name not in window_themes(self._load_themes(), lgd.path / 'themes'):
            raise ValueError(f'No theme named "{name}"')
        lgd.config.set('Heirloom', 'window_theme', name)
        lgd.save_config()
        return self.themes()

    def _close(self) -> None:
        self._jobs.stop_downloads()

    def _lgd(self) -> LGDLFS:
        return LGDLFS(config_file=self._config_file)

    def _command(self, job: Job) -> list[str]:
        config = ['-c', self._config_file] if self._config_file else []
        target = [job.app_name] if job.app_name else []
        with self._lock:
            # without a login only offline launches work, so try that rather than fail
            offline = ['--offline'] if job.kind == 'play' and not self._user else []
        return [*self._heirloom(), *config, *COMMANDS[job.kind], *target, *offline]

    def _title(self, app_name: str) -> str:
        with self._lock:
            return next((game['title'] for game in self._games if game['app_name'] == app_name), app_name)

    def _job_finished(self, job: Job) -> None:
        if job.kind == 'login' and job.status == 'done':
            self.refresh()
        elif job.kind in DOWNLOADS:
            self._read_library()

    def _read_library(self) -> None:
        lgd = self._lgd()
        games = read_library(lgd)
        user = logged_in_user(lgd)
        with self._lock:
            self._games, self._user = games, user

    def _update_games(self) -> str:
        """Starts the updates of installed games by themselves, and says which"""
        if self._lgd().config.getboolean('Heirloom', 'disable_auto_updates', fallback=False):
            return ''
        # games being played or updated, and updates stopped or failed while the window is open: Stop means stop,
        # and a failing update (a full disk, say) waits for the Update button rather than failing every hour
        skip = {job['app_name'] for job in self._jobs.snapshot()
                if job['status'] in ('queued', 'running') or (job['kind'] == 'install' and job['status'] != 'done')}
        with self._lock:
            games = [game for game in self._games if game['update'] and game['app_name'] not in skip]
        for game in games:
            self._jobs.add('install', game['app_name'], game['title'])
        return f'Updating by itself: {", ".join(game["title"] for game in games)}.' if games else ''

    def _refresh(self) -> None:
        notice, update, refreshed = '', None, False
        try:
            from heirloom.core import HeirloomCore
            core = HeirloomCore(override_config=self._config_file)
            if not logged_in_user(core.lgd):
                notice = 'Log in to see your games.'
            elif not core.login():
                notice = 'Could not log in, try logging in again.'
            else:
                core.get_game_and_dlc_list(update_assets=True)
                # games the Epic Games Launcher installed are added, rather than offered for download again
                if imported := core.egl_import_new():
                    titles = ', '.join(core.get_installed_game(app_name).title for app_name in imported)
                    notice = f'Added from the Epic Games Launcher: {titles}.'
                refreshed = True
            # logging in checks for a newer Heirloom
            if core.update_available and core.update_notice_enabled() and (release := core.get_update_info()):
                update = {'version': release['version'], 'name': release['name'], 'url': release['gh_url']}
        except Exception as e:
            log.warning(f'Refreshing the library failed: {e!r}')
            notice = f'Refreshing the library failed: {e}'
        self._read_library()
        # only with the latest versions just fetched, which needs the login to have worked
        if refreshed:
            notice = ' '.join(filter(None, (notice, self._update_games())))
        with self._lock:
            self._notice, self._update, self._refreshing = notice, update, False


def run(config_file: str | None, load_themes: Callable[[], dict[str, Theme]], background: bool = False) -> None:
    """
    Opens the window, or brings back the one already open. With the tray (Windows), closing the window hides it
    and Heirloom keeps going, downloads and updates included, until Quit in the tray's menu; background starts it
    hidden there.
    """
    import webview

    api = GuiApi(config_file, load_themes)
    tray = Tray.available()
    # the window, once there is one: a second "heirloom gui" may ask for it before
    opened: list[webview.Window] = []

    def show() -> None:
        for window in opened:
            window.show()
            window.restore()

    if not claim_window(api._lgd().path / 'window.port', show):
        return
    window = webview.create_window('Heirloom', url=str(WEB / 'index.html'), js_api=api, width=1280, height=820,
                                   min_size=(760, 560), background_color='#01211a', hidden=background and tray)
    assert window is not None
    opened.append(window)
    quitting = threading.Event()

    def closing() -> bool:
        if not tray or quitting.is_set():
            return True
        window.hide()
        return False

    def quit_heirloom() -> None:
        quitting.set()
        window.destroy()

    window.events.closing += closing
    if tray:
        Tray(show, quit_heirloom).start()

    def refresh_hourly() -> None:
        # new versions turn up while Heirloom keeps going, and their updates start by themselves
        while not quitting.wait(60 * 60):
            api.refresh()

    threading.Thread(target=refresh_hourly, daemon=True).start()
    try:
        webview.start()
    finally:
        quitting.set()
        api._close()
