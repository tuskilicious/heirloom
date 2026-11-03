"""
Heirloom installing its own new releases on Windows: the installer of the release is downloaded and checked, and run
silently once Heirloom has quit, which reopens it in the tray. Only for a copy that came from that installer.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from heirloom.gui.background import starts_with_windows

DOWNLOAD_PREFIX = 'https://github.com/tuskilicious/heirloom/releases/download/'
# the installer upgrades the copy it finds, and keeps the choices made when it was first installed; it leaves running
# programs alone, and failing leaves the old version to reopen. Paths are given as variables, so nothing needs quoting
INSTALL = '''
Wait-Process -Id $env:HL_PID -ErrorAction SilentlyContinue
Start-Process $env:HL_SETUP -ArgumentList $env:HL_ARGUMENTS -Wait
Start-Process $env:HL_REOPEN -ArgumentList '--background'
'''


def installed_by_setup() -> bool:
    uninstaller = Path(sys.executable).with_name('unins000.exe')
    return sys.platform == 'win32' and bool(getattr(sys, 'frozen', False)) and uninstaller.exists()


def other_heirlooms_running() -> bool:
    """Whether another heirloom.exe uses the files to replace: a game started from a shortcut, or a download"""
    output = subprocess.run(['tasklist', '/fi', 'imagename eq heirloom.exe', '/fo', 'csv', '/nh'], capture_output=True,
                            text=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    return output.lower().count('heirloom.exe') > 1


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


def start_install(setup: Path) -> None:
    """Starts what installs setup once this process has ended, and reopens Heirloom; this process should quit next"""
    arguments = ['/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCANCEL', '/NOCLOSEAPPLICATIONS',
                 f'/LOG="{setup.with_suffix(".log")}"']
    # the installer would turn this back on if it was on when first installed
    if not starts_with_windows():
        arguments.append('/MERGETASKS="!startup"')
    env = os.environ | {'HL_PID': str(os.getpid()), 'HL_SETUP': str(setup), 'HL_ARGUMENTS': ' '.join(arguments),
                        'HL_REOPEN': str(Path(sys.executable).with_name('heirloom-gui.exe'))}
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_BREAKAWAY_FROM_JOB', 0)
    subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-Command', INSTALL], env=env,
                     creationflags=flags)
