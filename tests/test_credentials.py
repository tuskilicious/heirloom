"""The Epic login tokens are kept with DPAPI on Windows or in the system keyring, not in user.json."""
import json
import sys

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from heirloom.core import HeirloomCore
from heirloom.lfs.credentials import DpapiStore, KeyringStore, default_credential_store
from heirloom.lfs.lgndry import LGDLFS

LOGIN = {'account_id': 'abc', 'displayName': 'Tester', 'expires_at': '2099-01-01T00:00:00.000Z',
         'access_token': 'eg1~access', 'refresh_token': 'eg1~refresh'}
PUBLIC = {key: value for key, value in LOGIN.items() if not key.endswith('_token')}


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        super().__init__()
        self.entries = {}

    def get_password(self, service, username):
        return self.entries.get((service, username))

    def set_password(self, service, username, password):
        self.entries[service, username] = password

    def delete_password(self, service, username):
        if self.entries.pop((service, username), None) is None:
            raise PasswordDeleteError(username)


class BrokenStore:
    name = 'a broken store'

    def load(self, *tokens):
        raise OSError('keyring is locked')

    save = delete = load


@pytest.fixture
def memory_keyring():
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def secure_store(lgd_home, request):
    """This system's own store: the real DPAPI on Windows, a keyring in memory elsewhere"""
    if sys.platform != 'win32':
        request.getfixturevalue('memory_keyring')


def user_json(lgd_home):
    return json.loads((lgd_home / 'user.json').read_text())


def test_default_store_for_this_system(tmp_path, memory_keyring):
    if sys.platform == 'win32':
        assert isinstance(default_credential_store(tmp_path), DpapiStore)
    else:
        assert isinstance(default_credential_store(tmp_path), KeyringStore)


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows always has DPAPI')
def test_without_a_keyring_tokens_stay_in_user_json(lgd_home):
    # conftest turns the keyring off
    assert default_credential_store(lgd_home) is None
    with LGDLFS().userdata_lock as lock:
        lock.data = LOGIN
    assert user_json(lgd_home) == LOGIN


def test_login_tokens_are_kept_out_of_user_json(secure_store, lgd_home):
    with LGDLFS().userdata_lock as lock:
        lock.data = LOGIN
    assert user_json(lgd_home) == PUBLIC
    assert not any(b'eg1~' in path.read_bytes() for path in lgd_home.rglob('*') if path.is_file())
    assert LGDLFS().userdata == LOGIN

    with LGDLFS().userdata_lock as lock:
        lock.data = LOGIN | {'access_token': 'eg1~refreshed'}
    assert LGDLFS().userdata['access_token'] == 'eg1~refreshed'

    LGDLFS().invalidate_userdata()
    assert not (lgd_home / 'user.json').exists()
    assert LGDLFS().credential_store.load() is None


def test_plaintext_login_is_moved_into_the_store(secure_store, lgd_home):
    lgd_home.mkdir()
    (lgd_home / 'user.json').write_text(json.dumps(LOGIN))
    assert LGDLFS().userdata == LOGIN
    assert user_json(lgd_home) == PUBLIC
    assert LGDLFS().userdata == LOGIN


def test_login_stays_in_user_json_when_the_store_cannot_save_it(lgd_home, caplog):
    lgd = LGDLFS()
    lgd.credential_store = BrokenStore()
    with lgd.userdata_lock as lock:
        lock.data = LOGIN
    assert user_json(lgd_home) == LOGIN
    assert 'stays in user.json unencrypted' in caplog.text


def test_unreadable_store_logs_out_without_deleting_the_login(lgd_home, caplog):
    lgd_home.mkdir()
    (lgd_home / 'user.json').write_text(json.dumps(PUBLIC))
    core = HeirloomCore()
    core.lgd.credential_store = BrokenStore()

    assert core.lgd.userdata == PUBLIC, 'offline launches still know the account'
    with pytest.raises(ValueError, match='No saved credentials'):
        core.login()
    assert user_json(lgd_home) == PUBLIC
    assert 'Could not read your saved login from a broken store' in caplog.text

    core.lgd.invalidate_userdata()
    assert not (lgd_home / 'user.json').exists(), 'logging out works even so'


@pytest.mark.skipif(sys.platform != 'win32', reason='DPAPI is Windows only')
def test_dpapi_store(tmp_path):
    store = DpapiStore(tmp_path / 'user.dpapi')
    assert store.load() is None
    store.save({'refresh_token': 'eg1~refresh'})
    assert b'eg1~refresh' not in store.path.read_bytes()
    assert store.load() == {'refresh_token': 'eg1~refresh'}

    store.path.write_bytes(b'not encrypted by DPAPI')
    with pytest.raises(OSError):
        store.load()
    store.delete()
    store.delete()
    assert not store.path.exists()


def test_keyring_store_has_one_entry_per_config_folder(memory_keyring):
    first, second = KeyringStore('/config/first'), KeyringStore('/config/second')
    first.save({'refresh_token': 'eg1~refresh'})
    assert first.load() == {'refresh_token': 'eg1~refresh'}
    assert second.load() is None
    first.delete()
    first.delete()
    assert memory_keyring.entries == {}
