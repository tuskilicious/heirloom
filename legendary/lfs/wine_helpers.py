import configparser
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger('WineHelpers')


def read_registry(wine_pfx: str | os.PathLike[str]) -> configparser.ConfigParser:
    reg = configparser.ConfigParser(comment_prefixes=(';', '#', '/', 'WINE'), allow_no_value=True, strict=False)
    reg.optionxform = str  # type: ignore[assignment,method-assign]
    reg.read(Path(wine_pfx, 'user.reg'))
    return reg


def get_shell_folders(registry: configparser.ConfigParser, wine_pfx: str) -> dict[str, str]:
    folders = dict()
    for k, v in registry['Software\\\\Microsoft\\\\Windows\\\\CurrentVersion\\\\Explorer\\\\Shell Folders'].items():
        path_cleaned = v.strip('"').strip().replace('\\\\', '/').replace('C:/', '')
        folders[k.strip('"').strip()] = str(Path(wine_pfx, 'drive_c', path_cleaned))
    return folders


def case_insensitive_file_search(path: str | os.PathLike[str]) -> Path:
    """
    Similar to case_insensitive_path_search: Finds a file case-insensitively
    No-op on Windows
    """
    path = Path(path)
    if sys.platform == 'win32' or path.exists():
        return path

    path_parts = Path(os.path.normpath(path)).parts
    computed_path = Path(path_parts[0])
    for part in path_parts[1:]:
        # If the computed directory does not exist, add all remaining parts as-is to at least return a valid path
        # at the end
        if not computed_path.exists():
            computed_path /= part
            continue

        # First try to find an exact match, otherwise a case-insensitive one
        if not (computed_path / part).exists():
            part = next((x.name for x in computed_path.iterdir() if x.name.lower() == part.lower()), part)
        computed_path /= part
    return computed_path


def case_insensitive_path_search(path: str) -> Path:
    """
    Attempts to find a path case-insensitively
    """
    # Legendary's save path resolver always returns absolute paths, so this is not as horrible as it looks
    path_parts = path.replace('\\', '/').split('/')
    path_parts[0] = '/'
    # filter out empty parts
    path_parts = [i for i in path_parts if i]

    # attempt to find lowest level directory that exists case-sensitively
    longest_path = Path()
    remaining_parts: list[str] = []
    for i in range(len(path_parts), 0, -1):
        if Path(*path_parts[:i]).exists():
            longest_path = Path(*path_parts[:i])
            remaining_parts = path_parts[i:]
            break
    logger.debug(f'Longest valid path: {longest_path}')
    logger.debug(f'Remaining parts: {remaining_parts}')

    # Iterate over remaining parts, find matching directories case-insensitively
    still_remaining: list[str] = []
    for idx, part in enumerate(remaining_parts):
        for item in longest_path.iterdir():
            if item.is_dir() and item.name.lower() == part.lower():
                longest_path = item
                break
        else:
            # once we stop finding parts break
            still_remaining = remaining_parts[idx:]
            break

    logger.debug(f'New longest path: {longest_path}')
    logger.debug(f'Still unresolved: {still_remaining}')
    final_path = longest_path.joinpath(*still_remaining)
    logger.debug(f'Final path: {final_path}')
    return final_path.resolve()
