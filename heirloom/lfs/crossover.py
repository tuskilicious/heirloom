import logging
import plistlib
import subprocess
from pathlib import Path

_logger = logging.getLogger('CXHelpers')


def _bottles_path() -> Path:
    return Path.home() / 'Library' / 'Application Support' / 'CrossOver' / 'Bottles'


def mac_get_crossover_version(app_path: str) -> str | None:
    try:
        plist = plistlib.loads(Path(app_path, 'Contents', 'Info.plist').read_bytes())
        return plist['CFBundleShortVersionString']
    except Exception as e:
        _logger.debug(f'Failed to load plist for "{app_path}" with {e!r}')
        return None


def mac_find_crossover_apps() -> list[tuple[str, str]]:
    paths = ['/Applications/CrossOver.app']
    try:
        out = subprocess.check_output(['mdfind', 'kMDItemCFBundleIdentifier="com.codeweavers.CrossOver"'])
        paths.extend(out.decode('utf-8', 'replace').strip().split('\n'))
    except Exception as e:
        _logger.warning(f'Trying to find CrossOver installs via mdfind failed: {e!r}')

    valid = [p for p in paths if Path(p, 'Contents', 'Info.plist').exists()]
    found_tuples = set()

    for path in valid:
        version = mac_get_crossover_version(path)
        if not version:
            continue
        _logger.debug(f'Found Crossover {version} at "{path}"')
        found_tuples.add((version, path))

    return sorted(found_tuples, reverse=True)


def mac_get_crossover_bottles() -> list[str]:
    if not _bottles_path().exists():
        return []
    return sorted(p.name for p in _bottles_path().iterdir() if mac_is_valid_bottle(p.name))


def mac_is_valid_bottle(bottle_name: str) -> bool:
    return (_bottles_path() / bottle_name / 'cxbottle.conf').exists()


def mac_get_bottle_path(bottle_name: str) -> str:
    return str(_bottles_path() / bottle_name)


def mac_is_crossover_running() -> bool:
    try:
        out = subprocess.check_output(['launchctl', 'list'])
        return b'com.codeweavers.CrossOver.' in out
    except Exception as e:
        _logger.warning(f'Getting list of running application bundles failed: {e!r}')
        return True  # assume the worst
