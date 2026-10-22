import logging
from datetime import datetime, timezone
from fnmatch import fnmatch
from hashlib import sha1
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryFile

from heirloom.lfs.utils import StrPath
from heirloom.models.chunk import Chunk
from heirloom.models.manifest import (
    ChunkInfo,
    ChunkPart,
    FileManifest,
    Manifest,
)


def _filename_matches(filename, patterns):
    """
    Helper to determine if a filename matches the filter patterns

    :param filename: name of the file
    :param patterns: list of patterns to match against
    :return:
    """

    for pattern in patterns:
        # Pattern is a directory, just check if path starts with it
        if pattern.endswith('/') and filename.startswith(pattern):
            return True
        # Check if pattern is a suffix of filename
        if filename.endswith(pattern):
            return True
        # Check if pattern with wildcards ('*') matches
        if fnmatch(filename, pattern):
            return True

    return False


class SaveGameHelper:
    def __init__(self):
        self.files = dict()
        self.log = logging.getLogger('SGH')

    def finalize_chunk(self, chunk: Chunk) -> ChunkInfo:
        assert chunk.sha_hash is not None, 'chunk data must be set before finalizing'
        ci = ChunkInfo()
        ci.guid = chunk.guid
        ci.hash = chunk.hash
        ci.sha_hash = chunk.sha_hash
        # use a temporary file for uploading
        _tmp_file = TemporaryFile()
        self.files[ci.path] = _tmp_file
        # write() returns file size and also sets the uncompressed size
        ci.file_size = chunk.write(_tmp_file)
        ci.window_size = chunk.uncompressed_size
        _tmp_file.seek(0)
        return ci

    def package_savegame(self, input_folder: str, app_name: str = '', epic_id: str = '',
                         cloud_folder: str = '', cloud_folder_mac: str = '',
                         include_filter: list | None = None,
                         exclude_filter: list | None = None,
                         manifest_dt: datetime | None = None):
        """
        :param input_folder: Folder to be packaged into chunks/manifest
        :param app_name: App name for savegame being stored
        :param epic_id: Epic account ID
        :param cloud_folder: Folder the savegame resides in (based on game metadata)
        :param cloud_folder_mac: Folder the macOS savegame resides in (based on game metadata)
        :param include_filter: list of patterns for files to include (excludes all others)
        :param exclude_filter: list of patterns for files to exclude (includes all others)
        :param manifest_dt: datetime for the manifest name (optional)
        :return:
        """
        m = Manifest()
        # create metadata for savegame
        m.meta.app_name = f'{app_name}{epic_id}'
        if not manifest_dt:
            manifest_dt = datetime.now(timezone.utc)
        m.meta.build_version = manifest_dt.strftime('%Y.%m.%d-%H.%M.%S')
        m.custom_fields['CloudSaveFolder'] = cloud_folder
        if cloud_folder_mac:
            m.custom_fields['CloudSaveFolder_MAC'] = cloud_folder_mac

        self.log.info(f'Packing savegame for "{app_name}", input folder: {input_folder}')
        files = self._find_files(input_folder, include_filter, exclude_filter)
        if not files:
            if exclude_filter or include_filter:
                self.log.warning('No save files matching the specified filters have been found.')
            return self.files

        chunk_num = 0
        cur_chunk: Chunk | None = None
        cur_buffer = BytesIO()

        for _file, f_rel in sorted(files, key=lambda f: str(f[0]).casefold()):
            s = _file.stat()
            f = FileManifest()
            f.filename = f_rel
            self.log.debug(f'Processing file "{f.filename}"')
            f.file_size = s.st_size
            fhash = sha1()

            with _file.open('rb') as cf:
                while remaining := s.st_size - cf.tell():
                    if not cur_chunk:  # create new chunk
                        cur_chunk = Chunk()
                        cur_buffer = BytesIO()
                        chunk_num += 1

                    # create chunk part and write it to chunk buffer
                    cp = ChunkPart(guid=cur_chunk.guid, offset=cur_buffer.tell(),
                                   size=min(remaining, 1024 * 1024 - cur_buffer.tell()),
                                   file_offset=cf.tell())
                    _tmp = cf.read(cp.size)
                    if not _tmp:
                        self.log.warning(f'Got EOF for "{f.filename}" with {remaining} bytes remaining! '
                                         f'File may have been corrupted/modified.')
                        break

                    cur_buffer.write(_tmp)
                    fhash.update(_tmp)  # update sha1 hash with new data
                    f.chunk_parts.append(cp)

                    if cur_buffer.tell() >= 1024 * 1024:
                        cur_chunk.data = cur_buffer.getvalue()
                        ci = self.finalize_chunk(cur_chunk)
                        self.log.info(f'Chunk #{chunk_num} "{ci.path}" created')
                        # add chunk to CDL
                        m.chunk_data_list.elements.append(ci)
                        cur_chunk = None

            f.hash = fhash.digest()
            m.file_manifest_list.elements.append(f)

        # write remaining chunk if it exists
        if cur_chunk:
            cur_chunk.data = cur_buffer.getvalue()
            ci = self.finalize_chunk(cur_chunk)
            self.log.info(f'Chunk #{chunk_num} "{ci.path}" created')
            m.chunk_data_list.elements.append(ci)
            cur_buffer.close()

        # Finally write/serialize manifest into another temporary file
        _m_filename = f'manifests/{m.meta.build_version}.manifest'
        _tmp_file = TemporaryFile()
        _m_size = m.write(_tmp_file)
        _tmp_file.seek(0)
        self.log.info(f'Manifest "{_m_filename}" written ({_m_size} bytes)')
        self.files[_m_filename] = _tmp_file

        # return dict with created files for uploading/whatever
        return self.files

    def get_deletion_list(self, save_folder: StrPath, include_filter: list[str] | None = None,
                          exclude_filter: list[str] | None = None) -> list[str]:
        return [rel for _, rel in self._find_files(save_folder, include_filter, exclude_filter)]

    def _find_files(self, folder: StrPath, include_filter: list[str] | None,
                    exclude_filter: list[str] | None) -> list[tuple[Path, str]]:
        """Files below folder that pass the filters, as (path, folder-relative POSIX path) pairs"""
        files = []
        for _file_path in Path(folder).rglob('*'):
            if not _file_path.is_file():
                continue
            _file_path_rel = _file_path.relative_to(folder).as_posix()

            if include_filter and not _filename_matches(_file_path_rel, include_filter):
                self.log.debug(f'Excluding "{_file_path_rel}" (does not match include filter)')
                continue
            elif exclude_filter and _filename_matches(_file_path_rel, exclude_filter):
                self.log.debug(f'Excluding "{_file_path_rel}" (does match exclude filter)')
                continue

            files.append((_file_path, _file_path_rel))

        return files
