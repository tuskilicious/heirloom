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
import shlex
import shutil
import subprocess
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from heirloom.downloader.queue import heirloom_command, start_job, stop_job
from heirloom.downloader.throttle import parse_speed
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
from heirloom.utils.env import is_windows_mac_or_pyi

if TYPE_CHECKING:
    from heirloom.core import HeirloomCore

log = logging.getLogger('GUI')

WEB = Path(__file__).parent / 'web'
# plugins that come with Heirloom, to install from the window
STORE = Path(__file__).parent.parent / 'store'
# the window's own look, Keeper Light, in web/style.css
WINDOW_THEME = 'heirloom'
# switches in Settings, and the config options they turn the other way: each is on unless disabled
SWITCHES = {'cloud_saves': 'disable_cloud_save_sync', 'auto_updates': 'disable_auto_updates',
            'update_notice': 'disable_update_notice'}
SPEEDS = ('max_download_speed', 'max_download_speed_while_playing')
# Epic's public list of the games given away now and next
FREE_GAMES = 'https://store-site-backend-static-ipv4.ak.epicgames.com/freeGamesPromotions'
STORE_PAGE = 'https://store.epicgames.com/p/'
# folder dialogs, in pywebview's numbering (webview.FileDialog.FOLDER in newer ones)
FOLDER_DIALOG = 20
# how the window shows the library, kept between runs in window.json: the first of each is the default
VIEW_CHOICES = {'filter': ('all', 'installed', 'updates'), 'sort': ('title', 'recent', 'played', 'size')}
# portrait art first, as the library shows covers
COVER_TYPES = ('DieselGameBoxTall', 'OfferImageTall', 'DieselStoreFrontTall', 'Thumbnail', 'DieselGameBox')
# covers are drawn at most this big, at twice their size on screen: hundreds of originals are slow to decode
COVER_SIZE = (440, 586)
# Epic's image servers, which resize on request
RESIZABLE = ('cdn1.epicgames.com', 'cdn2.unrealengine.com')
# landscape art for the banner of the game played last
ART_TYPES = ('DieselGameBox', 'DieselStoreFrontWide', 'OfferImageWide')

# downloads (and uninstalls, repairs, moves and imports) run one at a time, as heirloom changes only one game's
# install at a time
DOWNLOADS = ('install', 'uninstall', 'repair', 'overlay', 'move', 'import')
COMMANDS = {
    'install': ['-y', 'install'],
    'uninstall': ['-y', 'uninstall'],
    'repair': ['-y', 'repair'],
    'move': ['-y', 'move'],
    # with the game's DLC that is there too
    'import': ['-y', 'import'],
    # the save folder Epic gives is used, as --yes alone skips games without one chosen yet
    'sync': ['-y', 'sync-saves', '--accept-path'],
    # all the Ubisoft games of the account at once, which is how Epic activates them
    'activate': ['-y', 'activate', '--uplay'],
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


def image_url(game: Game | None, kinds: tuple[str, ...], size: tuple[int, int] | None = None) -> str:
    """The first of kinds a game has an image of; at size (width, height) when Epic's image server can resize it"""
    images = {image.get('type'): image.get('url') for image in game.metadata.get('keyImages', [])} if game else {}
    url = next((images[kind] for kind in kinds if images.get(kind)), '')
    if url and size and urlparse(url).hostname in RESIZABLE:
        width, height = size
        url += f'{"&" if "?" in url else "?"}h={height}&quality=medium&resize=1&w={width}'
    return url


def open_in_file_manager(path: str | Path) -> None:
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])


def free_games(country: str, locale: str, owned: set[str]) -> list[dict[str, Any]]:
    """
    The games Epic gives away now and next: title, cover, store page, whether it is free now (or from start),
    until when, and whether it is in the library already (by namespace, from owned)
    """
    import requests
    response = requests.get(FREE_GAMES, params={'locale': locale, 'country': country, 'allowCountries': country},
                            headers={'User-Agent': 'Heirloom'}, timeout=20)
    response.raise_for_status()
    found = []
    for element in response.json()['data']['Catalog']['searchStore']['elements']:
        promotions = element.get('promotions') or {}
        # free is a promotion at 100% off; the rest of the list are sales and leftovers
        offers = {kind: [offer for group in promotions.get(key) or [] for offer in group['promotionalOffers']
                         if offer['discountSetting']['discountPercentage'] == 0]
                  for kind, key in (('now', 'promotionalOffers'), ('next', 'upcomingPromotionalOffers'))}
        if not (offer := next(iter(offers['now'] or offers['next']), None)):
            continue
        mappings = (element.get('catalogNs') or {}).get('mappings') or []
        slug = (element.get('productSlug') or next((m['pageSlug'] for m in mappings), '') or '').split('/')[0]
        images = {image['type']: image['url'] for image in element.get('keyImages') or []}
        found.append({
            'title': element['title'],
            'image': next((images[kind] for kind in ('OfferImageTall', 'Thumbnail', 'DieselStoreFrontTall')
                           if kind in images), ''),
            # only a store page of Epic's, whatever the list says
            'url': STORE_PAGE + slug if re.fullmatch(r'[a-z0-9-]+', slug) else 'https://store.epicgames.com/free-games',
            'now': bool(offers['now']), 'start': offer['startDate'], 'end': offer['endDate'],
            'owned': element.get('namespace') in owned,
        })
    # free now first, then by when
    return sorted(found, key=lambda game: (not game['now'], game['start']))


def free_space(folder: str) -> int | None:
    """The bytes free on the drive of folder, which need not exist yet; None if there is no telling"""
    path = Path(folder).expanduser()
    for candidate in (path, *path.parents):
        if candidate.exists():
            try:
                return shutil.disk_usage(candidate).free
            except OSError:
                return None
    return None


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
    # your achievements of the games Heirloom asked Epic about, by namespace: None for games with none unlocked
    unlocked = lgd.achievements or {}
    metas = {app_name: lgd.get_game_meta(app_name) for app_name in set(lgd.get_game_app_names()) | set(installed)}
    # how much DLC with files of its own each game has, by the game's catalog id
    downloadable = {app_name for _, app_name in latest}
    dlcs = Counter(game.metadata.get('mainGameItem', {}).get('id') for game in metas.values()
                   if game and game.is_dlc and game.app_name in downloadable)
    games = []
    for app_name, game in metas.items():
        igame = installed.get(app_name)
        if game and game.is_dlc:
            continue
        version = latest.get((igame.platform if igame else 'Windows', app_name))
        sessions = playtime.get(app_name, [])
        games.append({
            'app_name': app_name,
            'title': game.app_title if game else igame.title if igame else app_name,
            'cover': image_url(game, COVER_TYPES, COVER_SIZE),
            'art': image_url(game, ART_TYPES),
            'installed': igame is not None,
            'version': igame.version if igame else version,
            'update': bool(igame and version and version != igame.version),
            'size': igame.install_size if igame else None,
            'store': game.third_party_store if game else None,
            'ubisoft': bool(game and game.partner_link_type == 'ubisoft'),
            'cloud_saves': bool(game and game.supports_cloud_saves),
            'dlcs': dlcs[game.catalog_item_id] if game and game.catalog_item_id else 0,
            # seconds played, and when the last session ended
            'played': round(sum(session.duration.total_seconds() for session in sessions)),
            'last_played': max(session.end for session in sessions).isoformat() if sessions else None,
            # how many it has, and how many you unlocked if known
            'achievements': {
                'total': game.achievements.total_achievements,
                'unlocked': (unlocked[game.namespace] or {}).get('totalUnlocked', 0) if game.namespace in unlocked else None,
            } if game and game.achievements and game.achievements.total_achievements else None,
        })
    return sorted(games, key=lambda game: game['title'].lower())


def fetch_achievements(core: HeirloomCore, app_names: list[str]) -> None:
    """Asks Epic which achievements of these games you unlocked, one call each, and keeps that for the cards"""
    for app_name in app_names:
        game = core.get_game(app_name)
        if not game or not game.achievements or not game.achievements.total_achievements:
            continue
        try:
            core.get_user_achievements(game.namespace, update=True)
        except Exception as e:
            # the counts are a nicety: the library refreshes without them
            log.warning(f'Could not get the achievements of {app_name}: {e!r}')


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
    # what was chosen for it, such as an install's folder and DLC, as heirloom's options
    options: list[str] = field(default_factory=list)


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

    def add(self, kind: str, app_name: str, title: str, options: list[str] | None = None) -> None:
        with self._lock:
            self._jobs.append(Job(len(self._jobs) + 1, kind, app_name, title, options=options or []))
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
        self._free_games: list[dict[str, Any]] = []
        # counts the changes to the games and free games, so the page is sent them only when they changed
        self._revision = 0
        # when the latest versions of the games were last fetched (time.monotonic), 0 for not yet
        self._fetched = 0.0
        self._jobs = Jobs(self._command, self._job_finished)
        # the library is read while the window opens, and the page's first state() waits for it
        self._read = threading.Event()
        threading.Thread(target=self._read_library, daemon=True).start()

    def state(self, revision: int | None = None) -> dict[str, Any]:
        """What the page shows; the games are left out when the page has this revision of them already"""
        self._read.wait()
        with self._lock:
            state = {'user': self._user, 'refreshing': self._refreshing, 'notice': self._notice,
                     'update': self._update, 'revision': self._revision, 'jobs': self._jobs.snapshot()}
            if revision != self._revision:
                state |= {'games': self._games, 'free_games': self._free_games}
            return state

    def refresh(self) -> None:
        with self._lock:
            if self._refreshing:
                return
            self._refreshing = True
        threading.Thread(target=self._refresh, daemon=True).start()

    def play(self, app_name: str) -> None:
        self._jobs.add('play', app_name, self._title(app_name))

    def install_info(self, app_name: str) -> dict[str, Any]:
        """
        What installing a game takes, for the install dialog: its download and size on disk, its DLC, and the
        install folder with the space free there. It asks Epic, as "heirloom info" does, so it takes a moment.
        """
        config = ['-c', self._config_file] if self._config_file else []
        result = subprocess.run([*self._heirloom(), *config, 'info', app_name, '--json'], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=120,
                                env=os.environ | {'PYTHONIOENCODING': 'utf-8'},
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            info = json.loads(result.stdout[result.stdout.index('{'):])
        except ValueError:
            raise ValueError(f'Could not find out what {self._title(app_name)} takes to install') from None
        manifest, game = info.get('manifest') or {}, info.get('game') or {}
        folder = self.settings()['install_dir']
        return {
            'download_size': manifest.get('download_size'), 'disk_size': manifest.get('disk_size'),
            # only DLC with files of its own: the rest comes with the game
            'dlcs': [dlc['title'] for dlc in game.get('owned_dlc') or [] if dlc.get('installable')],
            'folder': folder, 'free': free_space(folder),
        }

    def free_space(self, folder: str) -> int | None:
        return free_space(folder)

    def open_store(self, url: str) -> None:
        """Opens a game's page on the Epic Games Store in the browser, to claim it there"""
        if not url.startswith('https://store.epicgames.com/'):
            raise ValueError('Only pages of the Epic Games Store open from here')
        import webbrowser
        webbrowser.open(url)

    def launch_options(self, app_name: str) -> str:
        """The arguments a game starts with besides its own (start_params in its section of the config)"""
        return self._lgd().config.get(app_name, 'start_params', fallback='')

    def set_launch_options(self, app_name: str, options: str) -> str:
        options = options.strip()
        # what launching will do with them, so a stray quote is caught here rather than then
        shlex.split(options)
        lgd = self._lgd()
        if options:
            if not lgd.config.has_section(app_name):
                lgd.config.add_section(app_name)
            lgd.config.set(app_name, 'start_params', options)
        elif lgd.config.has_option(app_name, 'start_params'):
            lgd.config.remove_option(app_name, 'start_params')
        lgd.save_config()
        return options

    def choose_folder(self, current: str) -> dict[str, Any] | None:
        """A folder for one install, from the system's folder dialog, with the space free there; None if cancelled"""
        import webview
        chosen = webview.windows[0].create_file_dialog(FOLDER_DIALOG, directory=current if Path(current).is_dir() else '')
        return {'folder': chosen[0], 'free': free_space(chosen[0])} if chosen else None

    def install(self, app_name: str, folder: str | None = None, dlcs: bool | None = None) -> None:
        """Installs a game, into folder (the install folder of Settings if None), with or without its DLC"""
        options = []
        if folder:
            if not Path(folder).is_absolute():
                raise ValueError('Choose a whole path for the install folder')
            options += ['--base-path', folder]
        if dlcs is not None:
            options.append('--with-dlcs' if dlcs else '--skip-dlcs')
        self._jobs.add('install', app_name, self._title(app_name), options)

    def uninstall(self, app_name: str) -> None:
        self._jobs.add('uninstall', app_name, self._title(app_name))

    def move(self, app_name: str, folder: str) -> None:
        """Moves an installed game into folder, on another drive too when there is room for it there"""
        if not Path(folder).is_absolute():
            raise ValueError('Choose a whole path to move it to')
        title, igame = self._title(app_name), self._lgd().get_installed_game(app_name)
        if not igame:
            raise ValueError(f'{title} is not installed')
        # on the same drive it is only renamed
        other_drive = Path(folder).anchor.lower() != Path(igame.install_path).anchor.lower()
        if other_drive and (free := free_space(folder)) is not None and free < igame.install_size:
            raise ValueError(f'Not enough space there: {title} takes {igame.install_size / 1024 ** 3:.1f} GiB')
        self._jobs.add('move', app_name, title, [folder])

    def import_game(self, app_name: str, folder: str) -> None:
        """Adds a game that is already in folder (from another PC or a backup, say) rather than downloading it"""
        if not Path(folder).is_absolute():
            raise ValueError("Choose a whole path for the game's folder")
        self._jobs.add('import', app_name, self._title(app_name), [folder])

    def dlcs(self, app_name: str) -> list[dict[str, Any]]:
        """The DLC of an installed game with files of its own, and whether each is installed, from the cached files"""
        lgd = self._lgd()
        game, igame = lgd.get_game_meta(app_name), lgd.get_installed_game(app_name)
        if not game or not igame:
            return []
        # Epic's list of what the account can download, DLC included; DLC without files of its own isn't in it
        owned = {asset.app_name for asset in (lgd.assets or {}).get(igame.platform, [])}
        installed = {dlc.app_name for dlc in lgd.get_installed_list() if dlc.is_dlc}
        dlcs = [dlc for dlc in map(lgd.get_game_meta, lgd.get_game_app_names())
                if dlc and dlc.is_dlc and dlc.app_name in owned
                and dlc.metadata.get('mainGameItem', {}).get('id') == game.catalog_item_id]
        return [{'app_name': dlc.app_name, 'title': dlc.app_title, 'installed': dlc.app_name in installed}
                for dlc in sorted(dlcs, key=lambda dlc: dlc.app_title.lower())]

    def save_status(self, app_name: str) -> dict[str, Any]:
        """
        Whether a game's saves on this PC or in the cloud are newer, and when each was made. It asks Epic, as
        "heirloom sync-saves" does, so it takes a moment.
        """
        from heirloom.core import HeirloomCore
        core = HeirloomCore(override_config=self._config_file)
        igame = core.get_installed_game(app_name)
        if not igame or not core.login(quick=True):
            raise ValueError('Could not ask Epic about the cloud saves')
        saves = sorted(core.get_save_games(app_name), key=lambda save: save.datetime)
        folder = igame.save_path or core.get_save_path(app_name, platform=igame.platform)
        status, (local, cloud) = core.check_savegame_state(folder, saves[-1] if saves else None)
        return {'status': status.name.lower(), 'folder': folder,
                'local': local.isoformat() if local else None, 'cloud': cloud.isoformat() if cloud else None}

    def achievements(self, app_name: str) -> dict[str, Any] | None:
        """
        A game's achievements and which you unlocked: unlocked ones first, newest first, then the ones in progress,
        then the rest. It asks Epic for yours, so it takes a moment; None for a game without achievements.
        """
        from heirloom.core import HeirloomCore
        core = HeirloomCore(override_config=self._config_file)
        game = core.get_game(app_name)
        if not game or not core.login(quick=True):
            raise ValueError('Could not ask Epic about the achievements')
        found = core.get_achievements(game, update=True)
        # the card's count too
        self._read_library()
        if not found:
            return None
        return {
            'unlocked': found['user_unlocked'], 'total': found['total_achievements'],
            'xp': found['user_xp'], 'total_xp': found['total_product_xp'],
            'achievements': [{
                'name': item['display_name'], 'description': item['description'], 'icon': item['icon_link'],
                'unlocked': item['unlocked'], 'progress': item['progress'], 'xp': item['xp'],
                'date': item['unlock_date'].isoformat() if item['unlock_date'] else None,
                # the share of players who have it, in percent
                'rarity': (item['rarity'] or {}).get('percent'),
            } for item in found['completed'] + found['in_progress'] + found['uninitiated']],
            # hidden ones are only counted, so they stay a surprise
            'hidden': len(found['hidden']),
        }

    def activate_ubisoft(self) -> None:
        self._jobs.add('activate', '', 'Ubisoft Connect')

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

    def settings(self) -> dict[str, Any]:
        """The options Settings shows: where games go, download speeds in MiB/s (0 for none), and switches"""
        config = self._lgd().config
        speeds = {}
        for option in SPEEDS:
            try:
                speeds[option] = round(parse_speed(config.get('Heirloom', option, fallback='0')) / 1024 ** 2, 2)
            except ValueError:
                speeds[option] = 0
        # the update notice is off by default where Heirloom comes from a package manager, which updates it
        defaults = {'update_notice': not is_windows_mac_or_pyi()}
        return {
            'install_dir': str(Path(config.get('Heirloom', 'install_dir', fallback='~/Games')).expanduser()),
            **speeds,
            **{name: not config.getboolean('Heirloom', option, fallback=defaults.get(name, False))
               for name, option in SWITCHES.items()},
            **self.background(),
        }

    def set_setting(self, name: str, value: Any) -> dict[str, Any]:
        """Changes one option of Settings in the config file; a value that makes no sense is refused"""
        if name == 'starts_with_windows':
            start_with_windows(value is True)
            return self.settings()
        # a fresh read of the config, so changes heirloom made to it meanwhile are kept
        lgd = self._lgd()
        if name == 'install_dir':
            folder = Path(str(value)).expanduser()
            if not str(value).strip() or not folder.is_absolute():
                raise ValueError('Choose a whole path for the install folder')
            lgd.config.set('Heirloom', 'install_dir', str(folder))
        elif name in SPEEDS:
            speed = str(value).strip() or '0'
            parse_speed(speed)
            lgd.config.set('Heirloom', name, speed)
        elif name in SWITCHES and isinstance(value, bool):
            lgd.config.set('Heirloom', SWITCHES[name], str(not value).lower())
        else:
            raise ValueError(f'No setting named "{name}"')
        lgd.save_config()
        return self.settings()

    def choose_install_dir(self) -> dict[str, Any]:
        """Asks for the install folder with the system's folder dialog, and keeps the choice"""
        current = self.settings()['install_dir']
        chosen = self.choose_folder(current)
        return self.set_setting('install_dir', chosen['folder']) if chosen else self.settings()

    def background(self) -> dict[str, Any]:
        """Whether Heirloom keeps going in the tray, and whether it starts with Windows (only from the installer)"""
        return {'tray': Tray.available(), 'startup_possible': startup_command() is not None,
                'starts_with_windows': starts_with_windows()}

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
        self._read.wait()
        with self._lock:
            # without a login only offline launches work, so try that rather than fail
            offline = ['--offline'] if job.kind == 'play' and not self._user else []
            # with the latest versions fetched within the hour and no update for the game, heirloom need not
            # fetch them again before it starts the game
            fresh = time.monotonic() - self._fetched < 60 * 60 if self._fetched else False
            current = fresh and any(game['app_name'] == job.app_name and game['installed'] and not game['update']
                                    for game in self._games)
            skip = ['--skip-version-check'] if job.kind == 'play' and self._user and current else []
        return [*self._heirloom(), *config, *COMMANDS[job.kind], *target, *job.options, *offline, *skip]

    def _title(self, app_name: str) -> str:
        self._read.wait()
        with self._lock:
            title = next((game['title'] for game in self._games if game['app_name'] == app_name), None)
        # DLC isn't in the library
        game = self._lgd().get_game_meta(app_name) if title is None and app_name else None
        return title or (game.app_title if game else app_name)

    def _job_finished(self, job: Job) -> None:
        if job.kind == 'login' and job.status == 'done':
            self.refresh()
        elif job.kind in DOWNLOADS:
            self._read_library()
        elif job.kind == 'play':
            # achievements are unlocked while playing
            threading.Thread(target=self._played, args=(job.app_name,), daemon=True).start()

    def _played(self, app_name: str) -> None:
        try:
            from heirloom.core import HeirloomCore
            core = HeirloomCore(override_config=self._config_file)
            if core.login(quick=True):
                fetch_achievements(core, [app_name])
        except Exception as e:
            log.warning(f'Could not get the achievements of {app_name}: {e!r}')
        self._read_library()

    def _read_library(self) -> None:
        try:
            lgd = self._lgd()
            games = read_library(lgd)
            user = logged_in_user(lgd)
            with self._lock:
                if games != self._games:
                    self._games = games
                    self._revision += 1
                self._user = user
        finally:
            self._read.set()

    def _update_games(self) -> str:
        """Starts the updates of installed games by themselves, and says which"""
        if self._lgd().config.getboolean('Heirloom', 'disable_auto_updates', fallback=False):
            return ''
        # games being played or updated, and updates stopped or failed while the window is open: Stop means stop,
        # and a failing update (a full disk, say) waits for the Update button rather than failing every hour
        self._read.wait()
        skip = {job['app_name'] for job in self._jobs.snapshot()
                if job['status'] in ('queued', 'running') or (job['kind'] == 'install' and job['status'] != 'done')}
        with self._lock:
            games = [game for game in self._games if game['update'] and game['app_name'] not in skip]
        for game in games:
            self._jobs.add('install', game['app_name'], game['title'])
        return f'Updating by itself: {", ".join(game["title"] for game in games)}.' if games else ''

    def _refresh(self) -> None:
        notice, update, refreshed, fetched = '', None, False, 0.0
        try:
            from heirloom.core import HeirloomCore
            core = HeirloomCore(override_config=self._config_file)
            if not logged_in_user(core.lgd):
                notice = 'Log in to see your games.'
            elif not core.login():
                notice = 'Could not log in, try logging in again.'
            else:
                core.get_game_and_dlc_list(update_assets=True)
                fetched = time.monotonic()
                try:
                    owned = {game.namespace for game in map(core.lgd.get_game_meta, core.lgd.get_game_app_names())
                             if game and game.namespace}
                    free = free_games(core.country_code, f'{core.language_code}-{core.country_code}', owned)
                    with self._lock:
                        if free != self._free_games:
                            self._free_games = free
                            self._revision += 1
                except Exception as e:
                    # the free games are a nicety: the library refreshes without them
                    log.warning(f'Could not get the free games: {e!r}')
                # games the Epic Games Launcher installed are added, rather than offered for download again
                fetch_achievements(core, [igame.app_name for igame in core.get_installed_list()])
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
            with self._lock:
                self._fetched = fetched
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

    config_dir = api._lgd().path
    port_file = config_dir / 'window.port'
    if not claim_window(port_file, show):
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
        # a profile of its own that is kept, so covers come from the disk cache rather than Epic each time
        webview.start(private_mode=False, storage_path=str(config_dir / 'webview'))
    finally:
        quitting.set()
        api._close()
        # the next "heirloom gui" need not ask a window that is gone
        port_file.unlink(missing_ok=True)
