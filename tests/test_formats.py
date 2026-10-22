import hashlib
import os
from datetime import datetime

from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad

from heirloom.models.chunk import Chunk
from heirloom.models.manifest import Manifest, ManifestComparison
from heirloom.utils.egl_crypt import decrypt_epic_data
from heirloom.utils.savegame_helper import SaveGameHelper


def _make_save(root):
    (root / 'slots').mkdir(parents=True)
    files = {
        'slots/one.sav': os.urandom(1500 * 1024),
        'slots/two.sav': b'two',
        'settings.ini': b'[x]\n',
        'cache.tmp': b'junk',
    }
    for name, data in files.items():
        (root / name).write_bytes(data)
    return files


def _rebuild(manifest, chunk_files):
    chunks = {}
    for ci in manifest.chunk_data_list.elements:
        chunk_files[ci.path].seek(0)
        chunks[ci.guid_num] = Chunk.read_buffer(chunk_files[ci.path].read()).data
    return {
        fm.filename: b''.join(chunks[cp.guid_num][cp.offset:cp.offset + cp.size] for cp in fm.chunk_parts)
        for fm in manifest.file_manifest_list.elements
    }


def test_savegame_roundtrip_through_manifest_and_chunks(tmp_path):
    files = _make_save(tmp_path)
    out = SaveGameHelper().package_savegame(
        str(tmp_path), app_name='App', epic_id='acc', cloud_folder='{AppData}/Game',
        exclude_filter=['*.tmp'], manifest_dt=datetime(2024, 1, 2, 3, 4, 5))

    manifest_file = out.pop('manifests/2024.01.02-03.04.05.manifest')
    manifest_file.seek(0)
    manifest = Manifest.read_all(manifest_file.read())

    assert manifest.meta.app_name == 'Appacc'
    assert manifest.custom_fields['CloudSaveFolder'] == '{AppData}/Game'
    assert len(manifest.chunk_data_list.elements) == 2

    expected = {k: v for k, v in files.items() if not k.endswith('.tmp')}
    assert _rebuild(manifest, out) == expected
    for fm in manifest.file_manifest_list.elements:
        assert fm.hash == hashlib.sha1(expected[fm.filename]).digest()


def test_savegame_include_filter_and_deletion_list(tmp_path):
    _make_save(tmp_path)
    helper = SaveGameHelper()
    assert sorted(helper.get_deletion_list(str(tmp_path), include_filter=['slots/'])) == \
        ['slots/one.sav', 'slots/two.sav']
    assert helper.package_savegame(str(tmp_path), include_filter=['nothing']) == {}


def test_manifest_write_read_roundtrip_and_comparison(tmp_path):
    files = _make_save(tmp_path)
    out = SaveGameHelper().package_savegame(str(tmp_path))
    blob = next(f for name, f in out.items() if name.startswith('manifests/'))
    blob.seek(0)
    original = Manifest.read_all(blob.read())

    rewritten = Manifest.read_all(original.write())
    assert [f.filename for f in rewritten.file_manifest_list.elements] == \
        [f.filename for f in original.file_manifest_list.elements]

    diff = ManifestComparison.create(original, None)
    assert diff.added == set(files)
    assert not ManifestComparison.create(original, rewritten).changed


def test_decrypt_epic_data():
    key = 'A' * 32
    plaintext = 'username=player'
    encrypted = AES.new(key.encode(), AES.MODE_ECB).encrypt(pad(plaintext.encode(), 16))
    assert decrypt_epic_data(key, encrypted) == plaintext
