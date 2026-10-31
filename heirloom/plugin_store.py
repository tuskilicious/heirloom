"""
Heirloom's plugin repository, github.com/tuskilicious/heirloom-plugins: its index of the plugins there, and
installing or updating one by downloading the repository and keeping only that plugin's folder.
Only this repository is ever downloaded from.
"""
from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from heirloom.plugins import PluginManager, PluginManifest

REPOSITORY = 'tuskilicious/heirloom-plugins'
INDEX = f'https://raw.githubusercontent.com/{REPOSITORY}/main/index.json'
ARCHIVE = f'https://codeload.github.com/{REPOSITORY}/zip/refs/heads/main'
# the whole repository's zip, and one plugin's files unpacked
MAX_ARCHIVE = 20 * 1024 ** 2
MAX_PLUGIN = 5 * 1024 ** 2
NAME = re.compile(r'[a-z0-9][a-z0-9_-]*')
TIMEOUT = 10


def fetch_index() -> list[dict[str, str]]:
    """The plugins of the repository: name, common_name, description, version and folder of each"""
    response = requests.get(INDEX, timeout=TIMEOUT, headers={'User-Agent': 'Heirloom'})
    response.raise_for_status()
    plugins = response.json().get('plugins')
    if not isinstance(plugins, list):
        raise ValueError('The plugin index has no list of plugins')
    return [{key: str(entry.get(key, '')) for key in ('name', 'common_name', 'description', 'version', 'folder')}
            for entry in plugins
            if isinstance(entry, dict) and NAME.fullmatch(str(entry.get('name')))
            and NAME.fullmatch(str(entry.get('folder')))]


def newer(available: str, installed: str) -> bool:
    """Whether version available is newer than installed, as dotted numbers (any other difference counts too)"""
    def numbers(version: str) -> tuple[int, ...] | None:
        return tuple(map(int, version.split('.'))) if re.fullmatch(r'\d+(\.\d+)*', version) else None
    if (a := numbers(available)) is not None and (b := numbers(installed)) is not None:
        return a > b
    return available != installed


def install(plugins_folder: Path, name: str, index: list[dict[str, str]] | None = None) -> PluginManifest:
    """
    Installs plugin name from the repository, or updates the copy already there. The new copy is unpacked and checked
    beside the old one and only then takes its place, so a failure leaves the old copy as it was.
    """
    entry = next((entry for entry in index or fetch_index() if entry['name'] == name), None)
    if entry is None:
        raise ValueError(f'No plugin named "{name}" in the plugin repository')
    archive = _download(ARCHIVE)
    plugins_folder.mkdir(parents=True, exist_ok=True)
    staging = plugins_folder / f'.{name}.new'
    shutil.rmtree(staging, ignore_errors=True)
    try:
        _unpack(archive, entry['folder'], staging)
        manifest = PluginManifest.read(staging)
        if manifest.name != name:
            raise ValueError(f'The plugin in "{entry["folder"]}" is named "{manifest.name}", not "{name}"')
        found = PluginManager(plugins_folder).discover().get(name)
        target = found[0] if found else plugins_folder / name
        if target.exists():
            old = plugins_folder / f'.{name}.old'
            shutil.rmtree(old, ignore_errors=True)
            target.rename(old)
            staging.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        else:
            staging.rename(target)
        return manifest
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def remove(plugins_folder: Path, name: str) -> None:
    """Turns a plugin off and deletes its folder"""
    manager = PluginManager(plugins_folder)
    if not (found := manager.discover().get(name)):
        raise ValueError(f'No plugin named "{name}"')
    manager.set_enabled(name, False)
    shutil.rmtree(found[0])


def _download(url: str) -> bytes:
    with requests.get(url, timeout=TIMEOUT, stream=True, headers={'User-Agent': 'Heirloom'}) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(64 * 1024):
            data += chunk
            if len(data) > MAX_ARCHIVE:
                raise ValueError('The plugin repository is larger than expected')
    return bytes(data)


def _unpack(archive: bytes, folder: str, target: Path) -> None:
    """Unpacks the files of folder (inside the archive's one top folder) into target; nothing outside it, no links"""
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        members: list[tuple[PurePosixPath, Any]] = []
        for info in zipped.infolist():
            path = PurePosixPath(info.filename)
            # heirloom-plugins-main/<folder>/...
            if len(path.parts) < 3 or path.parts[1] != folder or info.is_dir():
                continue
            relative = PurePosixPath(*path.parts[2:])
            if relative.is_absolute() or '..' in relative.parts or '\\' in info.filename:
                raise ValueError(f'The plugin has a file outside its folder: {info.filename}')
            # the file type in the zip's Unix mode: symbolic links are refused
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError(f'The plugin has a link: {info.filename}')
            members.append((relative, info))
        if not members:
            raise ValueError(f'The plugin repository has no folder "{folder}"')
        if sum(info.file_size for _, info in members) > MAX_PLUGIN:
            raise ValueError('The plugin is larger than expected')
        for relative, info in members:
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(zipped.read(info))
