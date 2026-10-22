"""
Plugins, modelled on Millennium's: a folder with a plugin.json manifest and a Python backend
whose setup(plugin) subscribes to heirloom's events and adds commands.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import re
import sys
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from heirloom.models.game import InstalledGame, PlaytimeSession

if TYPE_CHECKING:
    from heirloom.core import HeirloomCore

logger = logging.getLogger('Plugins')


@dataclass
class GameLaunching:
    """
    Sent right before a game starts. Handlers may change command, environment and working_directory,
    and the game is started with whatever they hold afterwards.
    """
    app_name: str
    game: InstalledGame
    command: list[str]
    environment: dict[str, str]
    working_directory: str


@dataclass
class GameExited:
    """Sent when a game started by "heirloom launch" exits (or heirloom stops watching it)"""
    app_name: str
    session: PlaytimeSession


@dataclass
class GameInstalled:
    app_name: str
    game: InstalledGame


@dataclass
class GameUpdated:
    app_name: str
    game: InstalledGame
    previous_version: str


EVENTS: dict[str, type] = {
    'game_launching': GameLaunching,
    'game_exited': GameExited,
    'game_installed': GameInstalled,
    'game_updated': GameUpdated,
}

EventHandler = Callable[[Any], None]
CommandHandler = Callable[[argparse.Namespace, 'HeirloomCore'], None]


def install_event(app_name: str, game: InstalledGame,
                  previous_version: str | None) -> GameInstalled | GameUpdated | None:
    """The event for a finished install; None for a repair or install tag change that kept the version"""
    if previous_version is None:
        return GameInstalled(app_name, game)
    if previous_version != game.version:
        return GameUpdated(app_name, game, previous_version)
    return None


@dataclass
class PluginManifest:
    """plugin.json, with the fields of Millennium's plugin manifest that apply to a CLI"""
    name: str
    common_name: str
    description: str = ''
    version: str = ''
    backend: str = 'main.py'
    use_backend: bool = True
    # theme files (see heirloom.themes) this plugin provides while enabled
    themes: tuple[str, ...] = ()

    @classmethod
    def read(cls, folder: Path) -> PluginManifest:
        data = json.loads((folder / 'plugin.json').read_text(encoding='utf-8'))
        name = data.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', name):
            raise ValueError(f'"name" must be lowercase letters, digits, "-" and "_", got {name!r}')
        manifest = cls(name=name, common_name=data.get('common_name') or name,
                       description=data.get('description', ''), version=data.get('version', ''),
                       backend=data.get('backend') or 'main.py', use_backend=data.get('useBackend', True),
                       themes=tuple(data.get('themes', [])))
        for key, path in [('backend', manifest.backend), *(('themes', theme) for theme in manifest.themes)]:
            if not (folder / path).resolve().is_relative_to(folder.resolve()):
                raise ValueError(f'"{key}" must name files inside the plugin folder, got {path!r}')
        return manifest


class Plugin:
    """What a plugin's setup() receives"""

    def __init__(self, manifest: PluginManifest, folder: Path):
        self.manifest = manifest
        self.folder = folder
        self.log = logging.getLogger(f'plugin.{manifest.name}')
        self._handlers: list[tuple[type, EventHandler]] = []
        self._commands: dict[str, tuple[CommandHandler, argparse.ArgumentParser, str]] = {}

    def on(self, event: str, handler: EventHandler) -> None:
        if event not in EVENTS:
            raise ValueError(f'Unknown event "{event}", available events: {", ".join(EVENTS)}')
        self._handlers.append((EVENTS[event], handler))

    def command(self, name: str, handler: CommandHandler, help: str = '') -> argparse.ArgumentParser:
        """Adds "heirloom <name>"; add its options to the returned parser. handler(args, core) runs it."""
        parser = argparse.ArgumentParser(add_help=False)
        self._commands[name] = (handler, parser, help)
        return parser


class PluginManager:
    def __init__(self, folder: Path):
        self.folder = folder
        self.plugins: dict[str, Plugin] = {}
        self.errors: dict[str, str] = {}
        self.handlers: defaultdict[type, list[tuple[Plugin, EventHandler]]] = defaultdict(list)
        self.commands: dict[str, tuple[Plugin, CommandHandler]] = {}

    def discover(self) -> dict[str, tuple[Path, PluginManifest]]:
        found: dict[str, tuple[Path, PluginManifest]] = {}
        if not self.folder.is_dir():
            return found
        for folder in sorted(p for p in self.folder.iterdir() if p.is_dir()):
            try:
                manifest = PluginManifest.read(folder)
            except Exception as e:
                self.errors[folder.name] = f'invalid plugin.json: {e}'
                continue
            if manifest.name in found:
                self.errors[folder.name] = f'another plugin is already named "{manifest.name}"'
                continue
            found[manifest.name] = (folder, manifest)
        return found

    @property
    def _enabled_file(self) -> Path:
        return self.folder / 'enabled.json'

    def enabled(self) -> set[str]:
        try:
            return set(json.loads(self._enabled_file.read_text(encoding='utf-8')))
        except FileNotFoundError:
            return set()
        except ValueError as e:
            logger.error(f'Ignoring unreadable "{self._enabled_file}", no plugins are enabled: {e!r}')
            return set()

    def set_enabled(self, name: str, enabled: bool) -> None:
        names = self.enabled() | {name} if enabled else self.enabled() - {name}
        self.folder.mkdir(parents=True, exist_ok=True)
        self._enabled_file.write_text(json.dumps(sorted(names), indent=2), encoding='utf-8')

    def load(self, subparsers: Any) -> None:
        """Runs every enabled plugin's setup() and adds its commands to the CLI"""
        enabled = self.enabled()
        for name, (folder, manifest) in self.discover().items():
            if name not in enabled:
                continue
            plugin = Plugin(manifest, folder)
            try:
                if manifest.use_backend:
                    _import_backend(folder / manifest.backend, name).setup(plugin)
            except Exception as e:
                self.errors[name] = f'failed to load: {e!r}'
                logger.error(f'Plugin "{name}" failed to load: {e!r}',
                             exc_info=logger.isEnabledFor(logging.DEBUG))
                continue

            self.plugins[name] = plugin
            for event_type, handler in plugin._handlers:
                self.handlers[event_type].append((plugin, handler))
            for command, (command_handler, parser, help_text) in plugin._commands.items():
                if command in subparsers.choices:
                    logger.error(f'Plugin "{name}" cannot add command "{command}", it already exists')
                    continue
                subparsers.add_parser(command, parents=[parser], help=f'{help_text} [plugin: {name}]')
                self.commands[command] = (plugin, command_handler)

    def theme_files(self) -> list[tuple[str, Path]]:
        """Theme files of the loaded plugins, as (plugin name, path)"""
        return [(name, plugin.folder / theme) for name, plugin in self.plugins.items()
                for theme in plugin.manifest.themes]

    def emit(self, event: Any) -> None:
        for plugin, handler in self.handlers[type(event)]:
            try:
                handler(event)
            except Exception as e:
                logger.error(f'Plugin "{plugin.manifest.name}" failed to handle {type(event).__name__}: {e!r}',
                             exc_info=logger.isEnabledFor(logging.DEBUG))

    def run_command(self, args: argparse.Namespace, core: HeirloomCore) -> None:
        plugin, handler = self.commands[args.subparser_name]
        try:
            handler(args, core)
        except Exception as e:
            logger.error(f'Plugin "{plugin.manifest.name}" command "{args.subparser_name}" failed: {e!r}',
                         exc_info=logger.isEnabledFor(logging.DEBUG))


def _import_backend(path: Path, name: str) -> ModuleType:
    # loaded as a package rooted at the plugin folder, so the backend can import its own modules relatively
    module_name = f'heirloom_plugin_{name.replace("-", "_")}'
    spec = importlib.util.spec_from_file_location(module_name, path, submodule_search_locations=[str(path.parent)])
    if spec is None or spec.loader is None:
        raise ImportError(f'cannot load {path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
