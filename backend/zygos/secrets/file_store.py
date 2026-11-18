"""AES-256-GCM encrypted-file secret store.

Files ``secrets.enc`` (ciphertext) and ``secrets.key`` (32 random bytes) live in one
directory. Format: ``b"ZYGS" + version(1)`` header (also AES-GCM associated data),
12-byte nonce, ciphertext of UTF-8 JSON ``{handle: value}``. ``cryptography`` is
imported lazily. An unreadable or tampered file is never treated as empty.

Stability: Experimental.
"""

from __future__ import annotations

import contextlib
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from zygos.secrets.handles import validate_handle
from zygos.secrets.types import EXTRA_MISSING, SecretStoreCorrupt, SecretStoreUnavailable

_HEADER = b"ZYGS\x01"
_NONCE_LEN = 12
_KEY_LEN = 32
_CORRUPT = "secrets file failed its integrity check"


def _aesgcm() -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise SecretStoreUnavailable(EXTRA_MISSING) from exc
    return AESGCM


def path_exists(path: Path) -> bool:
    """``path.exists()`` with OSError (e.g. permission denied) as SecretStoreUnavailable."""
    try:
        return path.exists()
    except OSError as exc:
        raise SecretStoreUnavailable(f"can't check {path.name} ({type(exc).__name__})") from None


class EncryptedFileStore:
    name = "encrypted_file"

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.enc_path = self.directory / "secrets.enc"
        self.key_path = self.directory / "secrets.key"
        self._lock_path = self.directory / "secrets.lock"

    def __repr__(self) -> str:
        return f"EncryptedFileStore({self.directory})"

    # -- public API ---------------------------------------------------------

    def availability(self) -> str | None:
        try:
            _aesgcm()
            enc_exists = path_exists(self.enc_path)
            key_exists = enc_exists and path_exists(self.key_path)
        except SecretStoreUnavailable as exc:
            return str(exc)
        if enc_exists:
            if not key_exists:
                return "key file missing"
            if not os.access(self.key_path, os.R_OK):
                return "key file not readable"
        return None

    def key_file_loose(self) -> bool:
        if sys.platform == "win32":
            return False  # st_mode permission bits mean nothing there
        try:
            mode = stat.S_IMODE(os.stat(self.key_path).st_mode)
        except OSError:
            return False
        return bool(mode & 0o077)

    def get(self, handle: str) -> str | None:
        validate_handle(handle)
        if not path_exists(self.enc_path):
            return None
        return self._read(_aesgcm()).get(handle)

    def set(self, handle: str, value: str) -> None:
        validate_handle(handle)
        aes = _aesgcm()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecretStoreUnavailable(
                f"can't create the secrets directory ({type(exc).__name__})"
            ) from None
        with self._locked():
            data = self._read(aes) if path_exists(self.enc_path) else {}
            data[handle] = value
            self._write(aes, data)

    def delete(self, handle: str) -> None:
        validate_handle(handle)
        if not path_exists(self.enc_path):
            return
        aes = _aesgcm()
        with self._locked():
            if not path_exists(self.enc_path):
                return
            data = self._read(aes)
            if handle in data:
                del data[handle]
                self._write(aes, data)

    # -- internals ----------------------------------------------------------

    @contextlib.contextmanager
    def _locked(self) -> Iterator[None]:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if sys.platform == "win32":  # pragma: no cover
                # Windows: no cross-process lock; atomic os.replace still protects
                # file integrity, concurrent writers may lose an update.
                yield
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def _read_key(self, create: bool) -> bytes:
        try:
            key = self.key_path.read_bytes()
        except FileNotFoundError:
            if not create:
                raise SecretStoreUnavailable("key file missing") from None
            key = os.urandom(_KEY_LEN)
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(key)
                fh.flush()
                os.fsync(fh.fileno())
            return key
        except OSError as exc:
            raise SecretStoreUnavailable(f"key file not readable ({type(exc).__name__})") from exc
        if len(key) != _KEY_LEN:
            raise SecretStoreCorrupt("key file has the wrong size")
        return key

    def _read(self, aes: Any) -> dict[str, str]:
        try:
            blob = self.enc_path.read_bytes()
        except OSError as exc:
            raise SecretStoreUnavailable(
                f"secrets file unreadable ({type(exc).__name__})"
            ) from exc
        key = self._read_key(create=False)
        n = len(_HEADER)
        if blob[:n] != _HEADER or len(blob) < n + _NONCE_LEN + 16:
            raise SecretStoreCorrupt(_CORRUPT)
        nonce = blob[n : n + _NONCE_LEN]
        try:
            plain = aes(key).decrypt(nonce, blob[n + _NONCE_LEN :], _HEADER)
        except Exception as exc:  # InvalidTag carries no plaintext
            raise SecretStoreCorrupt(_CORRUPT) from exc
        data: Any = None
        try:
            data = json.loads(plain.decode("utf-8"))
        except ValueError:
            pass
        if data is None:
            # Decode errors hold the plaintext (.doc/.object); raised outside the
            # except block so they are neither the cause nor the context.
            raise SecretStoreCorrupt(_CORRUPT)
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in data.items()
        ):
            raise SecretStoreCorrupt(_CORRUPT)
        return data

    def _write(self, aes: Any, data: dict[str, str]) -> None:
        key = self._read_key(create=not path_exists(self.enc_path))
        nonce = os.urandom(_NONCE_LEN)
        ct = aes(key).encrypt(nonce, json.dumps(data).encode("utf-8"), _HEADER)
        fd, tmp_name = tempfile.mkstemp(dir=self.directory, prefix="secrets.enc.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(_HEADER + nonce + ct)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.enc_path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp.unlink()
            raise
