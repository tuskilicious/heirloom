"""
Heirloom getting its own new releases: the release's file is downloaded and checked here, and installed by the code for
this system in heirloom.desktop once Heirloom has quit.
"""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import requests

DOWNLOAD_PREFIX = 'https://github.com/tuskilicious/heirloom/releases/download/'


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_setup(setup: dict[str, str], path: Path) -> None:
    """Puts a release's installer at path, unless it's there already; there only once it matches GitHub's checksum"""
    digest = setup['sha256']
    if not setup['url'].startswith(DOWNLOAD_PREFIX) or not digest:
        raise ValueError(f'Not an installer to trust: {setup}')
    if path.exists() and _digest(path) == digest:
        return
    # installers of earlier releases go, and so does the record of trying them
    shutil.rmtree(path.parent, ignore_errors=True)
    path.parent.mkdir(parents=True)
    part = path.with_suffix('.part')
    with requests.get(setup['url'], stream=True, timeout=30) as response:
        response.raise_for_status()
        with part.open('wb') as file:
            for chunk in response.iter_content(1024 * 1024):
                file.write(chunk)
    if _digest(part) != digest:
        part.unlink()
        raise ValueError(f'The download of {path.name} does not match its checksum')
    part.replace(path)
