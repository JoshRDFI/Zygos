import os
import stat
import sys

import pytest

from secret_store.contract import SecretStoreContract
from zygos.secrets import EXTRA_MISSING, SecretStoreCorrupt, SecretStoreUnavailable
from zygos.secrets.file_store import EncryptedFileStore

H = "provider:anthropic"
SENT = "SENTINEL-9f3a-value"


@pytest.fixture
def store(tmp_path):
    return EncryptedFileStore(tmp_path / ".zygos")


class TestFileContract(SecretStoreContract):
    pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_first_set_creates_directory_and_0600_key(store):
    assert not store.key_path.parent.exists()
    store.set(H, "v")
    assert stat.S_IMODE(os.stat(store.key_path).st_mode) == 0o600
    assert store.get(H) == "v"


def test_ciphertext_does_not_contain_value(store):
    store.set(H, SENT)
    assert SENT.encode() not in store.enc_path.read_bytes()


def test_tampered_file_is_corrupt(store):
    store.set(H, "v")
    data = bytearray(store.enc_path.read_bytes())
    data[-1] ^= 0x01
    store.enc_path.write_bytes(bytes(data))
    before = store.enc_path.read_bytes()
    with pytest.raises(SecretStoreCorrupt):
        store.get(H)
    with pytest.raises(SecretStoreCorrupt):
        store.set(H, "other")
    assert store.enc_path.read_bytes() == before


def test_missing_key_with_existing_enc_is_unavailable(store):
    store.set(H, "v")
    store.key_path.unlink()
    with pytest.raises(SecretStoreUnavailable, match="key file missing"):
        store.get(H)
    with pytest.raises(SecretStoreUnavailable, match="key file missing"):
        store.set(H, "w")
    assert not store.key_path.exists()


def test_no_files_get_is_none_and_available(store):
    assert store.availability() is None
    assert store.get(H) is None
    assert not store.enc_path.exists()
    assert not store.key_path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_other_readable_key_reported_loose(store):
    store.set(H, "v")
    assert store.key_file_loose() is False
    os.chmod(store.key_path, 0o644)
    assert store.key_file_loose() is True
    assert store.get(H) == "v"


def test_without_cryptography_is_unavailable(store, monkeypatch):
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    assert store.availability() == EXTRA_MISSING
    with pytest.raises(SecretStoreUnavailable) as ei:
        store.set(H, "v")
    assert str(ei.value) == EXTRA_MISSING


def test_write_is_atomic(store, monkeypatch):
    store.set(H, "first")
    real = os.replace
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk")
        return real(*a, **k)

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.set(H, "second")
    assert store.get(H) == "first"
    assert list(store.directory.glob("*.tmp")) == []


def _encrypt_raw(store, plaintext: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    header = b"ZYGS\x01"
    nonce = os.urandom(12)
    key = store.key_path.read_bytes()
    store.enc_path.write_bytes(header + nonce + AESGCM(key).encrypt(nonce, plaintext, header))


@pytest.mark.parametrize("plain", [b"not json " + SENT.encode(), b"\xff\xfe" + SENT.encode()])
def test_bad_plaintext_is_corrupt_without_leaking_via_chain(store, plain):
    store.set(H, "v")
    _encrypt_raw(store, plain)
    with pytest.raises(SecretStoreCorrupt) as ei:
        store.get(H)
    assert SENT not in repr(ei.value.__cause__)
    assert SENT not in repr(ei.value.__context__)
    assert SENT not in str(ei.value)


@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs non-root POSIX")
def test_unreadable_enc_is_unavailable(store):
    store.set(H, "v")
    os.chmod(store.enc_path, 0o000)
    try:
        with pytest.raises(SecretStoreUnavailable, match="secrets file unreadable"):
            store.get(H)
        with pytest.raises(SecretStoreUnavailable, match="secrets file unreadable"):
            store.set(H, "w")
    finally:
        os.chmod(store.enc_path, 0o600)


def test_key_file_loose_is_false_on_windows(tmp_path, monkeypatch):
    import zygos.secrets.file_store as fs

    s = fs.EncryptedFileStore(tmp_path)
    s.key_path.write_bytes(b"k" * 32)
    s.key_path.chmod(0o644)
    assert s.key_file_loose() is True
    monkeypatch.setattr(fs.sys, "platform", "win32")
    assert s.key_file_loose() is False


def test_stat_error_is_unavailable(tmp_path, monkeypatch):
    pytest.importorskip("cryptography")
    from pathlib import Path

    import zygos.secrets.file_store as fs
    from zygos.secrets import SecretStoreUnavailable

    s = fs.EncryptedFileStore(tmp_path)

    def denied(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "exists", denied)
    with pytest.raises(SecretStoreUnavailable) as ei:
        s.get("provider:x")
    assert "PermissionError" in str(ei.value)
    assert "PermissionError" in s.availability()
