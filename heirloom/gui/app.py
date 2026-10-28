"""
"heirloom gui": a window over the game library. The page in web/ is shown by pywebview and calls GuiApi;
themes add their own CSS to it. Each action runs as its own "heirloom" process, as the download queue's jobs
do, so playtime, plugins and resumable downloads work just as they do in the terminal.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from heirloom.downloader.queue import heirloom_command, start_job, stop_job
from heirloom.lfs.lgndry import LGDLFS
from heirloom.models.game import Game
from heirloom.themes import DEFAULT_THEME, Theme

log = logging.getLogger('GUI')

WEB = Path(__file__).parent / 'web'
# portrait art first, as the library shows covers
COVER_TYPES = ('DieselGameBoxTall', 'OfferImageTall', 'DieselStoreFrontTall', 'Thumbnail', 'DieselGameBox')
# landscape art for the banner of the game played last
ART_TYPES = ('DieselGameBox', 'DieselStoreFrontWide', 'OfferImageWide')

# downloads (and uninstalls and repairs) run one at a time, as heirloom installs only one game at a time
DOWNLOADS = ('install', 'uninstall', 'repair')
COMMANDS = {
    'install': ['-y', 'install'],
    'uninstall': ['-y', 'uninstall'],
    'repair': ['-y', 'repair'],
    'sync': ['-y', 'sync-saves'],
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
        if sys.platform == 'win32':
            os.startfile(igame.install_path)
        else:
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', igame.install_path])

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

    def login(self) -> None:
        self._jobs.add('login', '', 'Epic Games account')

    def stop(self, job_id: int) -> None:
        self._jobs.stop(job_id)

    def themes(self) -> dict[str, Any]:
        themes = self._load_themes()
        name = self._lgd().config.get('Heirloom', 'theme', fallback=DEFAULT_THEME.name)
        active = themes.get(name, DEFAULT_THEME)
        return {'active': active.name, 'css': active.css,
                'themes': [{'name': theme.name, 'title': theme.common_name} for theme in themes.values()]}

    def use_theme(self, name: str) -> dict[str, Any]:
        if name not in self._load_themes():
            raise ValueError(f'No theme named "{name}"')
        # a fresh read of the config, so changes heirloom made to it meanwhile are kept
        lgd = self._lgd()
        lgd.config.set('Heirloom', 'theme', name)
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

    def _refresh(self) -> None:
        notice, update = '', None
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
            # logging in checks for a newer Heirloom
            if core.update_available and core.update_notice_enabled() and (release := core.get_update_info()):
                update = {'version': release['version'], 'name': release['name'], 'url': release['gh_url']}
        except Exception as e:
            log.warning(f'Refreshing the library failed: {e!r}')
            notice = f'Refreshing the library failed: {e}'
        self._read_library()
        with self._lock:
            self._notice, self._update, self._refreshing = notice, update, False


def run(config_file: str | None, load_themes: Callable[[], dict[str, Theme]]) -> None:
    import webview

    api = GuiApi(config_file, load_themes)
    webview.create_window('Heirloom', url=str(WEB / 'index.html'), js_api=api, width=1280, height=820,
                          min_size=(760, 560), background_color='#01211a')
    try:
        webview.start()
    finally:
        api._close()
