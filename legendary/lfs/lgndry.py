
import json
import logging
import os
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from time import time
from typing import Any

from filelock import FileLock

from legendary.models.config import LGDConf
from legendary.models.game import Game, GameAsset, InstalledGame, PlaytimeSession
from legendary.utils.aliasing import generate_aliases
from legendary.utils.env import is_windows_mac_or_pyi

from .utils import LockedJSONData, clean_filename

FILELOCK_DEBUG = False


def config_dir() -> Path:
    if config_path := os.environ.get('LEGENDARY_CONFIG_PATH'):
        return Path(config_path)
    if config_path := os.environ.get('XDG_CONFIG_HOME'):
        return Path(config_path, 'legendary')
    return Path('~/.config/legendary').expanduser()


class LGDLFS:
    def __init__(self, config_file: str | None = None):
        self.log = logging.getLogger('LGDLFS')
        self.path = config_dir()

        # EGS user info
        self._user_data: dict | None = None
        # EGS entitlements
        self._entitlements: list | None = None
        # EGS achievements
        self._achievements: dict | None = None
        # EGS asset data
        self._assets: dict[str, list[GameAsset]] | None = None
        # EGS metadata
        self._game_metadata: dict[str, dict] = dict()
        # Legendary update check info
        self._update_info: dict | None = None
        # EOS Overlay install/update check info
        self._overlay_update_info: dict | None = None
        self._overlay_install_info: InstalledGame | None = None
        # Config with game specific settings (e.g. start parameters, env variables)
        self.config = LGDConf(comment_prefixes='/', allow_no_value=True)

        if config_file:
            # if user specified a valid relative/absolute path use that,
            # otherwise create file in legendary config directory
            if Path(config_file).exists():
                self.config_path = Path(config_file).absolute()
            else:
                self.config_path = self.path / clean_filename(config_file)
            self.log.info(f'Using non-default config file "{self.config_path}"')
        else:
            self.config_path = self.path / 'config.ini'

        # ensure folders exist.
        for f in ['manifests', 'metadata', 'tmp']:
            (self.path / f).mkdir(parents=True, exist_ok=True)

        # if "old" folder exists migrate files and remove it
        manifests = self.path / 'manifests'
        old_manifests = manifests / 'old'
        if old_manifests.exists():
            self.log.info('Migrating manifest files from old folders to new, please wait...')
            # remove unversioned manifest files
            for _f in manifests.iterdir():
                if '.manifest' not in _f.name:
                    continue
                if '_' not in _f.name or (_f.name.startswith('UE_') and _f.name.count('_') < 2):
                    self.log.debug(f'Deleting "{_f.name}" ...')
                    _f.unlink()

            # move files from "old" to the base folder
            for _f in old_manifests.iterdir():
                try:
                    self.log.debug(f'Renaming "{_f.name}"')
                    _f.rename(manifests / _f.name)
                except Exception as e:
                    self.log.warning(f'Renaming manifest file "{_f.name}" failed: {e!r}')

            # remove "old" folder
            try:
                old_manifests.rmdir()
            except Exception as e:
                self.log.warning(f'Removing "{old_manifests}" folder failed: {e!r}, please remove manually')

        if not FILELOCK_DEBUG:
            # Prevent filelock logger from spamming Legendary debug output
            filelock_logger = logging.getLogger('filelock')
            filelock_logger.setLevel(logging.INFO)

        # try loading config
        try:
            self.config.read(self.config_path)
        except Exception as e:
            self.log.error(f'Unable to read configuration file, please ensure that file is valid! '
                           f'(Error: {repr(e)})')
            self.log.warning('Continuing with blank config in safe-mode...')
            self.config.read_only = True

        # make sure "Legendary" section exists
        if 'Legendary' not in self.config:
            self.config.add_section('Legendary')

        # Add opt-out options with explainers
        if not self.config.has_option('Legendary', 'disable_update_check'):
            self.config.set('Legendary', '; Disables the automatic update check')
            self.config.set('Legendary', 'disable_update_check', 'false')
        if not self.config.has_option('Legendary', 'disable_update_notice'):
            self.config.set('Legendary', '; Disables the notice about an available update on exit')
            self.config.set('Legendary', 'disable_update_notice', 'false' if is_windows_mac_or_pyi() else 'true')

        self._installed_lock = FileLock(self.path / 'installed.json.lock')

        try:
            self._installed: dict[str, dict] | None = self._load_json('installed.json')
        except Exception as e:
            self.log.debug(f'Loading installed games failed: {e!r}')
            self._installed = None

        # load existing app metadata
        for gm_file in (self.path / 'metadata').iterdir():
            try:
                _meta = json.loads(gm_file.read_text(encoding='utf-8'))
                self._game_metadata[_meta['app_name']] = _meta
            except Exception as e:
                self.log.debug(f'Loading game meta file "{gm_file.name}" failed: {e!r}')

        # load auto-aliases if enabled
        self.aliases: dict[str, str] = dict()
        if not self.config.getboolean('Legendary', 'disable_auto_aliasing', fallback=False):
            try:
                _j = self._load_json('aliases.json')
                for app_name, aliases in _j.items():
                    for alias in aliases:
                        self.aliases[alias] = app_name
            except Exception as e:
                self.log.debug(f'Loading aliases failed with {e!r}')

    def _load_json(self, name: str) -> Any:
        return json.loads((self.path / name).read_text(encoding='utf-8'))

    def _save_json(self, name: str, data: Any, **kwargs: Any) -> None:
        (self.path / name).write_text(json.dumps(data, indent=2, sort_keys=True, **kwargs), encoding='utf-8')

    @property
    @contextmanager
    def userdata_lock(self) -> Iterator[LockedJSONData]:
        """Wrapper around the lock to automatically update user data when it is released"""
        with LockedJSONData(self.path / 'user.json') as lock:
            try:
                yield lock
            finally:
                self._user_data = lock.data

    @property
    def userdata(self) -> dict | None:
        if self._user_data is not None:
            return self._user_data

        try:
            with self.userdata_lock as locked:
                return locked.data
        except Exception as e:
            self.log.debug(f'Failed to load user data: {e!r}')
            return None

    def invalidate_userdata(self) -> None:
        with self.userdata_lock as lock:
            lock.clear()

    @property
    def entitlements(self) -> list | None:
        if self._entitlements is not None:
            return self._entitlements

        try:
            self._entitlements = self._load_json('entitlements.json')
            return self._entitlements
        except Exception as e:
            self.log.debug(f'Failed to load entitlements data: {e!r}')
            return None

    @entitlements.setter
    def entitlements(self, entitlements: list) -> None:
        if entitlements is None:
            raise ValueError('Entitlements is none!')

        self._entitlements = entitlements
        self._save_json('entitlements.json', entitlements)

    @property
    def achievements(self) -> dict | None:
        if self._achievements is not None:
            return self._achievements

        try:
            self._achievements = self._load_json('achievements.json')
            return self._achievements
        except Exception as e:
            self.log.debug(f'Failed to load achievements data: {e!r}')
            return None

    @achievements.setter
    def achievements(self, achievements: dict) -> None:
        if achievements is None:
            raise ValueError('Achievements is none!')

        self._achievements = achievements
        self._save_json('achievements.json', achievements)

    @property
    def assets(self) -> dict[str, list[GameAsset]] | None:
        if self._assets is None:
            try:
                tmp = self._load_json('assets.json')
                self._assets = {k: [GameAsset.from_json(j) for j in v] for k, v in tmp.items()}
            except Exception as e:
                self.log.debug(f'Failed to load assets data: {e!r}')
                return None

        return self._assets

    @assets.setter
    def assets(self, assets: dict[str, list[GameAsset]]) -> None:
        if assets is None:
            raise ValueError('Assets is none!')

        self._assets = assets
        self._save_json('assets.json', {platform: [a.__dict__ for a in assets] for platform, assets in assets.items()})

    def _get_manifest_filename(self, app_name: str, version: str, platform: str | None = None) -> Path:
        if platform:
            fname = clean_filename(f'{app_name}_{platform}_{version}')
        else:
            fname = clean_filename(f'{app_name}_{version}')
        return self.path / 'manifests' / f'{fname}.manifest'

    def load_manifest(self, app_name: str, version: str, platform: str = 'Windows') -> bytes | None:
        try:
            return self._get_manifest_filename(app_name, version, platform).read_bytes()
        except FileNotFoundError:  # all other errors should propagate
            self.log.debug('Loading manifest failed, retrying without platform in filename...')
            try:
                return self._get_manifest_filename(app_name, version).read_bytes()
            except FileNotFoundError:  # all other errors should propagate
                return None

    def save_manifest(self, app_name: str, manifest, version: str, platform: str = 'Windows') -> None:
        with self._get_manifest_filename(app_name, version, platform).open('wb') as f:
            manifest.write(f)

    def get_game_meta(self, app_name: str) -> Game | None:
        if _meta := self._game_metadata.get(app_name, None):
            return Game.from_json(_meta)
        return None

    def set_game_meta(self, app_name: str, meta: Game) -> None:
        json_meta = meta.__dict__
        self._game_metadata[app_name] = json_meta
        self._save_json(f'metadata/{app_name}.json', json_meta)

    def delete_game_meta(self, app_name: str) -> None:
        if app_name not in self._game_metadata:
            raise ValueError(f'Game {app_name} does not exist in metadata DB!')

        del self._game_metadata[app_name]
        (self.path / 'metadata' / f'{app_name}.json').unlink(missing_ok=True)

    def get_game_app_names(self) -> list[str]:
        return sorted(self._game_metadata.keys())

    def get_tmp_path(self) -> Path:
        return self.path / 'tmp'

    def _delete_files(self, folder: str, keep=lambda _: False) -> None:
        for f in (self.path / folder).iterdir():
            if keep(f):
                continue
            try:
                f.unlink()
            except Exception as e:
                self.log.warning(f'Failed to delete file "{f.name}": {e!r}')

    def clean_tmp_data(self) -> None:
        self._delete_files('tmp')

    def clean_metadata(self, app_names) -> None:
        self._delete_files('metadata', keep=lambda f: f.stem in app_names)

    def clean_manifests(self, in_use) -> None:
        in_use_files = {
            f'{clean_filename(f"{app_name}_{version}")}.manifest'
            for app_name, version, _ in in_use
        }

        in_use_files |= {
            f'{clean_filename(f"{app_name}_{platform}_{version}")}.manifest'
            for app_name, version, platform in in_use
        }

        self._delete_files('manifests', keep=lambda f: f.name in in_use_files)

    def lock_installed(self) -> bool:
        """
        Locks the install data. We do not care about releasing this lock.
        If it is acquired by a Legendary instance it should own the lock until it exits.
        Some operations such as egl sync may be simply skipped if a lock cannot be acquired
        """
        if self._installed_lock.is_locked:
            return True

        try:
            self._installed_lock.acquire(blocking=False)
            # reload data in case it has been updated elsewhere
            try:
                self._installed = self._load_json('installed.json')
            except Exception as e:
                self.log.debug(f'Failed to load installed game data: {e!r}')

            return True
        except TimeoutError:
            return False

    def get_installed_game(self, app_name: str) -> InstalledGame | None:
        if self._installed is None:
            try:
                self._installed = self._load_json('installed.json')
            except Exception as e:
                self.log.debug(f'Failed to load installed game data: {e!r}')
                return None

        if game_json := self._installed.get(app_name, None):
            return InstalledGame.from_json(game_json)
        return None

    def set_installed_game(self, app_name: str, install_info: InstalledGame) -> None:
        if self._installed is None:
            self._installed = dict()

        if app_name in self._installed:
            self._installed[app_name].update(install_info.__dict__)
        else:
            self._installed[app_name] = install_info.__dict__

        self._save_json('installed.json', self._installed)

    def remove_installed_game(self, app_name: str) -> None:
        if self._installed is None:
            self.log.warning('Trying to remove a game, but no installed games?!')
            return

        if app_name in self._installed:
            del self._installed[app_name]
        else:
            self.log.warning(f'Trying to remove non-installed game: {app_name}')
            return

        self._save_json('installed.json', self._installed)

    def get_installed_list(self) -> list[InstalledGame]:
        if not self._installed:
            return []

        return [InstalledGame.from_json(i) for i in self._installed.values()]

    def save_config(self) -> None:
        # do not save if in read-only mode or file hasn't changed
        if self.config.read_only or not self.config.modified:
            return
        # if config file has been modified externally, back-up the user-modified version before writing
        if self.config_path.exists():
            if (modtime := int(self.config_path.stat().st_mtime)) != self.config.modtime:
                new_filename = f'config.{modtime}.ini'
                self.log.warning(f'Configuration file has been modified while legendary was running, '
                                 f'user-modified config will be renamed to "{new_filename}"...')
                self.config_path.rename(self.config_path.with_name(new_filename))

        with self.config_path.open('w') as cf:
            self.config.write(cf)

    @property
    def running_games_dir(self) -> Path:
        return self.path / 'running'

    def game_running_lock(self, app_name: str) -> FileLock:
        """Held while "legendary launch" waits for a game, so downloads can tell a game is running"""
        self.running_games_dir.mkdir(exist_ok=True)
        return FileLock(self.running_games_dir / f'{clean_filename(app_name)}-{os.getpid()}.lock')

    def add_playtime_session(self, app_name: str, session: PlaytimeSession) -> None:
        # locked, since several "legendary launch" processes may finish at the same time
        with LockedJSONData(self.path / 'playtime.json') as lock:
            data = lock.data or {}
            data.setdefault(app_name, []).append(session.to_json())
            lock.data = data

    def get_playtime(self) -> dict[str, list[PlaytimeSession]]:
        try:
            data = self._load_json('playtime.json')
        except FileNotFoundError:
            return {}
        return {app_name: [PlaytimeSession.from_json(s) for s in sessions] for app_name, sessions in data.items()}

    def get_dir_size(self) -> int:
        return sum(f.stat().st_size for f in self.path.glob('**/*') if f.is_file())

    def get_cached_version(self) -> dict:
        if self._update_info:
            return self._update_info

        try:
            self._update_info = self._load_json('version.json')
        except Exception as e:
            self.log.debug(f'Failed to load cached update data: {e!r}')
            self._update_info = dict(last_update=0, data=None)

        return self._update_info

    def set_cached_version(self, version_data) -> None:
        if not version_data:
            return
        self._update_info = dict(last_update=time(), data=version_data)
        self._save_json('version.json', self._update_info)

    def get_cached_sdl_data(self, app_name: str) -> dict | None:
        try:
            return self._load_json(f'tmp/{app_name}.json')
        except Exception as e:
            self.log.debug(f'Failed to load cached SDL data: {e!r}')
            return None

    def set_cached_sdl_data(self, app_name: str, sdl_version, sdl_data) -> None:
        if not app_name or not sdl_data:
            return
        self._save_json(f'tmp/{app_name}.json', dict(version=sdl_version, data=sdl_data))

    def get_cached_overlay_version(self) -> dict:
        if self._overlay_update_info:
            return self._overlay_update_info

        try:
            self._overlay_update_info = self._load_json('overlay_version.json')
        except Exception as e:
            self.log.debug(f'Failed to load cached Overlay update data: {e!r}')
            self._overlay_update_info = dict(last_update=0, data=None)

        return self._overlay_update_info

    def set_cached_overlay_version(self, version_data) -> None:
        self._overlay_update_info = dict(last_update=time(), data=version_data)
        self._save_json('overlay_version.json', self._overlay_update_info)

    def get_overlay_install_info(self) -> InstalledGame | None:
        if not self._overlay_install_info:
            try:
                self._overlay_install_info = InstalledGame.from_json(self._load_json('overlay_install.json'))
            except Exception as e:
                self.log.debug(f'Failed to load overlay install data: {e!r}')

        return self._overlay_install_info

    def set_overlay_install_info(self, igame: InstalledGame) -> None:
        self._overlay_install_info = igame
        self._save_json('overlay_install.json', vars(igame))

    def remove_overlay_install_info(self) -> None:
        try:
            self._overlay_install_info = None
            (self.path / 'overlay_install.json').unlink()
        except Exception as e:
            self.log.debug(f'Failed to delete overlay install data: {e!r}')

    def generate_aliases(self) -> None:
        self.log.debug('Generating list of aliases...')

        self.aliases = dict()
        aliases = set()
        collisions = set()
        alias_map: dict[str, set[str]] = defaultdict(set)

        for app_name in self._game_metadata:
            game = Game.from_json(self._game_metadata[app_name])
            if game.is_dlc:
                continue
            game_folder = game.metadata.get('customAttributes', {}).get('FolderName', {}).get('value', None)
            _aliases = generate_aliases(game.app_title, game_folder=game_folder, app_name=game.app_name)
            for alias in _aliases:
                if alias not in aliases:
                    aliases.add(alias)
                    alias_map[game.app_name].add(alias)
                else:
                    collisions.add(alias)

        # remove colliding aliases from map and add aliases to lookup table
        for app_name in alias_map:
            alias_map[app_name] -= collisions
            for alias in alias_map[app_name]:
                self.aliases[alias] = app_name

        def serialise_sets(obj):
            """Turn sets into sorted lists for storage"""
            return sorted(obj) if isinstance(obj, set) else obj

        self._save_json('aliases.json', alias_map, default=serialise_sets)
