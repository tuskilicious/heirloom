"""
Where the Epic login tokens are kept: encrypted with DPAPI on Windows (as the Epic Games Launcher does),
or in the system keyring on macOS and Linux. user.json keeps the rest of the login, which isn't secret.
"""
from __future__ import annotations

import json
import logging
import sys
from contextlib import suppress
from pathlib import Path

from .utils import LockedJSONData

TOKEN_KEYS = ('access_token', 'refresh_token')

log = logging.getLogger('Credentials')

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

    def _dpapi(data: bytes, encrypt: bool) -> bytes:
        # extra input to the encryption, so programs decrypting any DPAPI blob they find don't get this one
        entropy = b'Heirloom login'
        data_buffer = ctypes.create_string_buffer(data, len(data))
        entropy_buffer = ctypes.create_string_buffer(entropy, len(entropy))
        blob_in = _Blob(len(data), ctypes.cast(data_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_entropy = _Blob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        crypt = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
        # 0x1 is CRYPTPROTECT_UI_FORBIDDEN, never show a prompt
        if not crypt(ctypes.byref(blob_in), None, ctypes.byref(blob_entropy), None, None, 0x1,
                     ctypes.byref(blob_out)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
else:
    def _dpapi(data: bytes, encrypt: bool) -> bytes:
        raise OSError('DPAPI is only available on Windows')


class DpapiStore:
    """The tokens in a file that only the current Windows user can decrypt"""
    name = 'Windows DPAPI'

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict | None:
        try:
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return None
        return json.loads(_dpapi(encrypted, encrypt=False))

    def save(self, tokens: dict) -> None:
        partial = self.path.with_name(f'{self.path.name}.tmp')
        partial.write_bytes(_dpapi(json.dumps(tokens).encode(), encrypt=True))
        partial.replace(self.path)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)


class KeyringStore:
    """The tokens in the system keyring (macOS Keychain, Secret Service on Linux), one entry per config folder"""
    name = 'the system keyring'
    service = 'Heirloom'

    def __init__(self, account: str):
        import keyring
        import keyring.errors
        self._keyring = keyring
        self._not_found = keyring.errors.PasswordDeleteError
        self.account = account

    def load(self) -> dict | None:
        stored = self._keyring.get_password(self.service, self.account)
        return json.loads(stored) if stored else None

    def save(self, tokens: dict) -> None:
        self._keyring.set_password(self.service, self.account, json.dumps(tokens))

    def delete(self) -> None:
        with suppress(self._not_found):
            self._keyring.delete_password(self.service, self.account)


CredentialStore = DpapiStore | KeyringStore


def default_credential_store(config_path: Path) -> CredentialStore | None:
    """The secure store to use on this system, or None to keep the tokens in user.json"""
    if sys.platform == 'win32':
        return DpapiStore(config_path / 'user.dpapi')
    try:
        import keyring
        # no usable backend, e.g. no Secret Service on a headless machine, or turned off with
        # PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring
        if keyring.get_keyring().priority <= 0:
            return None
    except Exception as e:
        log.debug(f'No system keyring: {e!r}')
        return None
    return KeyringStore(str(config_path))


class UserDataLock(LockedJSONData):
    """
    user.json, with the login tokens moved out of it into a credential store when there is one.
    data holds the whole login as before, tokens included.
    """
    # set before entering; an argument to __init__ would be taken by FileLock's metaclass
    store: CredentialStore | None = None
    _stored_tokens: dict | None = None

    def __enter__(self):
        super().__enter__()
        self._stored_tokens = None
        # tokens still in user.json were saved before there was a store, or when saving to it failed;
        # they are used as they are and moved into the store on the way out
        if self.store and self._data and not any(key in self._data for key in TOKEN_KEYS):
            try:
                self._stored_tokens = self.store.load()
                if self._stored_tokens:
                    self._data = self._data | self._stored_tokens
            except Exception as e:
                # logged out until they can be read again, nothing is deleted
                log.warning(f'Could not read your saved login from {self.store.name}: {e!r}')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.store:
            self._move_tokens_to(self.store)
        super().__exit__(exc_type, exc_val, exc_tb)

    def _move_tokens_to(self, store: CredentialStore) -> None:
        if self._data is None:
            if self._initial_data is not None:
                try:
                    store.delete()
                except Exception as e:
                    log.warning(f'Could not remove your saved login from {store.name}: {e!r}')
            return

        tokens = {key: self._data[key] for key in TOKEN_KEYS if key in self._data}
        if not tokens:
            return
        if tokens != self._stored_tokens:
            try:
                store.save(tokens)
            except Exception as e:
                log.warning(f'Could not save your login to {store.name}, it stays in user.json '
                            f'unencrypted instead: {e!r}')
                return
        self._data = {key: value for key, value in self._data.items() if key not in TOKEN_KEYS}
