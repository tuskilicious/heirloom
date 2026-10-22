
import hashlib
import json
import logging
import os
import shutil
from collections.abc import Iterator
from pathlib import Path, PurePath
from sys import stdout
from time import perf_counter
from typing import Any

from filelock import FileLock

from legendary.lfs.wine_helpers import case_insensitive_file_search
from legendary.models.game import VerifyResult

logger = logging.getLogger('LFS Utils')

StrPath = str | os.PathLike[str]


def delete_folder(path: StrPath, recursive: bool = True) -> bool:
    try:
        logger.debug(f'Deleting "{path}", recursive={recursive}...')
        if not recursive:
            os.removedirs(path)
        else:
            shutil.rmtree(path)
    except Exception as e:
        logger.error(f'Failed deleting files with {e!r}')
        return False
    else:
        return True


def delete_filelist(path: StrPath, filenames: list[str],
                    delete_root_directory: bool = False,
                    silent: bool = False, case_insensitive: bool = True) -> bool:
    path = Path(path)
    dirs: set[PurePath] = set()
    no_error = True

    # delete all files that were installed
    for filename in filenames:
        _dir = PurePath(filename).parent
        if _dir.parts:
            dirs.add(_dir)

        try:
            full_path = path / filename
            if case_insensitive:
                full_path = case_insensitive_file_search(full_path)
            full_path.unlink()
        except Exception as e:
            if not silent:
                logger.error(f'Failed deleting file {filename} with {e!r}')
            no_error = False

    # add intermediate directories that would have been missed otherwise
    for _dir in list(dirs):
        dirs.update(p for p in _dir.parents if p.parts)

    # remove all directories, deepest first
    for _dir in sorted(dirs, key=lambda d: len(d.parts), reverse=True):
        try:
            dir_path = path / _dir
            if case_insensitive:
                dir_path = case_insensitive_file_search(dir_path)
            dir_path.rmdir()
        except FileNotFoundError:
            # directory has already been deleted, ignore that
            continue
        except Exception as e:
            if not silent:
                logger.error(f'Failed removing directory "{_dir}" with {e!r}')
            no_error = False

    if delete_root_directory:
        try:
            path.rmdir()
        except Exception as e:
            if not silent:
                logger.error(f'Removing game directory failed with {e!r}')

    return no_error


def validate_files(base_path: StrPath, filelist: list[tuple[str, str]], hash_type: str = 'sha1',
                   large_file_threshold: int = 1024 * 1024 * 512,
                   case_insensitive: bool = True) -> Iterator[tuple[VerifyResult, str, str, int]]:
    """
    Validates the files in filelist in path against the provided hashes

    :param base_path: path in which the files are located
    :param filelist: list of tuples in format (path, hash [hex])
    :param hash_type: (optional) type of hash, default is sha1
    :param large_file_threshold: (optional) threshold for large files, default is 512 MiB
    :param case_insensitive: (optional) whether to search for files case insensitively
    :return: yields tuples in format (VerifyResult, path, hash [hex], bytes read)
    """

    if not filelist:
        raise ValueError('No files to validate!')

    base_path = Path(base_path)
    if not base_path.exists():
        raise OSError('Path does not exist')

    for file_path, file_hash in filelist:
        full_path = base_path / file_path
        if case_insensitive:
            full_path = case_insensitive_file_search(full_path)
        # logger.debug(f'Checking "{file_path}"...')

        if not full_path.exists():
            yield VerifyResult.FILE_MISSING, file_path, '', 0
            continue

        show_progress = False
        interval = 0
        speed = 0.0
        start_time = 0.0

        try:
            _size = full_path.stat().st_size
            if _size > large_file_threshold:
                # enable progress indicator and go to new line
                stdout.write('\n')
                show_progress = True
                interval = max(1, int(_size / (1024 * 1024)) // 100)
                start_time = perf_counter()

            with full_path.open('rb') as f:
                real_file_hash = hashlib.new(hash_type)
                i = 0
                while chunk := f.read(1024*1024):
                    real_file_hash.update(chunk)
                    if show_progress and i % interval == 0:
                        pos = f.tell()
                        perc = (pos / _size) * 100
                        speed = pos / 1024 / 1024 / (perf_counter() - start_time)
                        stdout.write(f'\r=> Verifying large file "{file_path}": {perc:.0f}% '
                                     f'({pos / 1024 / 1024:.1f}/{_size / 1024 / 1024:.1f} MiB) '
                                     f'[{speed:.1f} MiB/s]\t')
                        stdout.flush()
                    i += 1

                if show_progress:
                    stdout.write(f'\r=> Verifying large file "{file_path}": 100% '
                                 f'({_size / 1024 / 1024:.1f}/{_size / 1024 / 1024:.1f} MiB) '
                                 f'[{speed:.1f} MiB/s]\t\n')

                result_hash = real_file_hash.hexdigest()
                if file_hash != result_hash:
                    yield VerifyResult.HASH_MISMATCH, file_path, result_hash, f.tell()
                else:
                    yield VerifyResult.HASH_MATCH, file_path, result_hash, f.tell()
        except Exception as e:
            logger.fatal(f'Could not verify "{file_path}"; opening failed with: {e!r}')
            yield VerifyResult.OTHER_ERROR, file_path, '', 0


def clean_filename(filename: str) -> str:
    return ''.join(i for i in filename if i not in '<>:"/\\|?*')


def get_dir_size(path: StrPath) -> int:
    return sum(f.stat().st_size for f in Path(path).glob('**/*') if f.is_file())


class LockedJSONData(FileLock):
    def __init__(self, lock_file: StrPath):
        self._file_path = Path(lock_file)
        super().__init__(self._file_path.with_name(self._file_path.name + '.lock'))

        self._data: Any = None
        self._initial_data: Any = None

    def __enter__(self):
        super().__enter__()

        if self._file_path.exists():
            self._data = json.loads(self._file_path.read_text(encoding='utf-8'))
            self._initial_data = self._data
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        super().__exit__(exc_type, exc_val, exc_tb)

        if self._data != self._initial_data:
            if self._data is not None:
                self._file_path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding='utf-8')
            else:
                self._file_path.unlink(missing_ok=True)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, new_data):
        if new_data is None:
            raise ValueError('Invalid new data, use clear() explicitly to reset file data')
        self._data = new_data

    def clear(self):
        self._data = None
