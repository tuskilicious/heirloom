import configparser
import json
import logging
import os
from pathlib import Path

from heirloom.models.egl import EGLManifest

logger = logging.getLogger('EGLFS')


def read_v2_installations(path: Path) -> dict[str, EGLManifest]:
    """
    Installed Windows games from the new Epic Games Launcher's installations.jsonl, by app name.

    The file is a log: a header line, then a record for every change to an installation. The latest
    record for an installation wins, and a {"deleted": true} record means it was uninstalled.
    """
    installations: dict[str, dict] = {}
    with path.open(encoding='utf-8') as f:
        for line_no, line in enumerate(f, start=1):
            try:
                record = json.loads(line)
            except ValueError:
                # e.g. a line the launcher was still writing
                logger.debug(f'Skipping unreadable line {line_no} of "{path}"')
                continue
            if not isinstance(record, dict) or 'installationId' not in record:
                continue
            if record.get('deleted'):
                installations.pop(record['installationId'], None)
            else:
                installations[record['installationId']] = record

    manifests = {}
    for record in installations.values():
        # incomplete ones are downloads that are running, paused or were cancelled
        if not record.get('complete') or not record.get('platform', 'Windows').startswith('Win'):
            continue
        if parent_id := record.get('parentInstallationId'):
            main_game = installations.get(parent_id, {}).get('artifactId', '')
        else:
            main_game = record['artifactId']
        manifest = EGLManifest.from_v2_installation(record, main_game)
        manifests[manifest.app_name] = manifest
    return manifests


class EPCLFS:
    # Known encryption key(s) for JSON user data
    # Data is encrypted using AES-256-ECB mode
    data_keys: list[str] = []

    def __init__(self):
        self.appdata_path: str | None = None
        self.programdata_path: str | None = None
        # installations.jsonl of the new (Tauri-based) launcher, which replaced the ProgramData manifests
        self.installations_path: str | None = None
        if os.name == 'nt':
            self.appdata_path = os.path.expandvars(
                r'%LOCALAPPDATA%\EpicGamesLauncher\Saved\Config\Windows'
            )
            self.programdata_path = os.path.expandvars(
                r'%PROGRAMDATA%\Epic\EpicGamesLauncher\Data\Manifests'
            )
            installations = Path(os.path.expandvars('%LOCALAPPDATA%'), 'com.epicgames.eglv2', 'installations.jsonl')
            if installations.exists() and not Path(self.programdata_path).is_dir():
                self.installations_path = str(installations)

        self.config = configparser.ConfigParser(strict=False)
        self.config.optionxform = str  # type: ignore[assignment,method-assign]

        self.manifests: dict[str, EGLManifest] = dict()

    def read_config(self):
        if not self.appdata_path:
            raise ValueError('EGS AppData path is not set')

        if not Path(self.appdata_path).is_dir():
            raise ValueError('EGS AppData path does not exist')

        self.config.read(Path(self.appdata_path, 'GameUserSettings.ini'), encoding='utf-8')

    def save_config(self):
        if not self.appdata_path:
            raise ValueError('EGS AppData path is not set')

        if not Path(self.appdata_path).is_dir():
            raise ValueError('EGS AppData path does not exist')

        with Path(self.appdata_path, 'GameUserSettings.ini').open('w', encoding='utf-8') as f:
            self.config.write(f, space_around_delimiters=False)

    def read_manifests(self):
        if self.installations_path:
            self.manifests = read_v2_installations(Path(self.installations_path))
            return

        if not self.programdata_path:
            raise ValueError('EGS ProgramData path is not set')

        if not Path(self.programdata_path).is_dir():
            # Not sure if we should `raise` here as well
            return

        for f in Path(self.programdata_path).glob('*.item'):
            data = json.loads(f.read_text(encoding='utf-8'))
            self.manifests[data['AppName']] = EGLManifest.from_json(data)

    def get_manifests(self) -> list[EGLManifest]:
        if not self.manifests:
            self.read_manifests()

        return list(self.manifests.values())

    def get_manifest(self, app_name) -> EGLManifest:
        if not self.manifests:
            self.read_manifests()

        if app_name in self.manifests:
            return self.manifests[app_name]
        else:
            raise ValueError('Cannot find manifest')

    def set_manifest(self, manifest: EGLManifest):
        if self.installations_path:
            raise ValueError('Adding games to the new Epic Games Launcher is not supported')
        if not self.programdata_path:
            raise ValueError('EGS ProgramData path is not set')

        if not Path(self.programdata_path).is_dir():
            raise ValueError('EGS ProgramData path does not exist')

        self.manifests[manifest.app_name] = manifest
        Path(self.programdata_path, f'{manifest.installation_guid}.item').write_text(
            json.dumps(manifest.to_json(), indent=4, sort_keys=True), encoding='utf-8')

    def delete_manifest(self, app_name):
        if self.installations_path:
            raise ValueError('Removing games from the new Epic Games Launcher is not supported')
        if not self.programdata_path:
            raise ValueError('EGS ProgramData path is not set')
        if not self.manifests:
            self.read_manifests()
        if app_name not in self.manifests:
            raise ValueError('AppName is not in manifests!')

        manifest = self.manifests.pop(app_name)
        Path(self.programdata_path, f'{manifest.installation_guid}.item').unlink()
