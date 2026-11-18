import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone

import pytest

from secret_store.fakes import FakeKeyring, backend_in
from zygos.config.schema import ZygosConfig
from zygos.secrets import (
    EXTRA_MISSING,
    InvalidHandle,
    Presence,
    SecretStoreUnavailable,
    build_secret_store,
)
from zygos.secrets.choice import ChoiceRecord, SqliteChoiceStore
from zygos.secrets.file_store import EncryptedFileStore

H = "provider:anthropic"
PROVISIONAL = "provisional — nothing saved yet"
FIXED_NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def _db(root):
    return root / ".zygos" / "preferences.db"


def _config(root, backend="auto"):
    return ZygosConfig.model_validate(
        {
            "personalization": {"db_path": str(_db(root))},
            "secrets": {"backend": backend},
        }
    )


def _ids():
    n = iter(range(1000))
    return lambda: f"id{next(n)}"


def _handle(root, backend="auto", keyring_backend=None):
    return build_secret_store(
        _config(root, backend),
        keyring_backend=keyring_backend,
        now=lambda: FIXED_NOW,
        new_id=_ids(),
    )


def _record(root, backend, install_id="old"):
    return SqliteChoiceStore(_db(root)).record_if_absent(
        ChoiceRecord(backend=backend, chosen_at="2026-11-01T00:00:00+00:00", install_id=install_id)
    )


def _read(root):
    return SqliteChoiceStore(_db(root)).read()


def _fail_keyring():
    return backend_in("keyring.backends.fail")


def test_config_explicit_file_wins_over_record(tmp_path):
    before = _record(tmp_path, "keyring")
    fake = FakeKeyring()
    h = _handle(tmp_path, "encrypted_file", fake)
    h.set(H, "v")
    assert fake.entries == {}
    assert EncryptedFileStore(_db(tmp_path).parent).get(H) == "v"
    assert h.get(H) == "v"
    st = h.status()
    assert (st.backend, st.reason, st.available) == ("encrypted_file", "set in config", True)
    assert st.location == str(_db(tmp_path).parent / "secrets.enc")
    assert _read(tmp_path) == before


def test_auto_provisional_prefers_keyring_and_records_on_first_set(tmp_path):
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    st = h.status()
    assert (st.backend, st.reason, st.available) == ("keyring", PROVISIONAL, True)
    assert h.get(H) is None
    assert _read(tmp_path) is None
    assert not _db(tmp_path).exists()
    h.set(H, "v")
    rec = _read(tmp_path)
    assert rec.backend == "keyring"
    assert fake.entries == {(f"zygos:{rec.install_id}", H): "v"}
    st = h.status()
    assert st.reason == "chosen 2026-11-17 at first save"
    assert st.location == f"zygos:{rec.install_id}"
    assert h.get(H) == "v"


def test_auto_provisional_falls_back_to_file_when_no_keychain(tmp_path):
    h = _handle(tmp_path, keyring_backend=_fail_keyring())
    st = h.status()
    assert (st.backend, st.reason, st.available) == ("encrypted_file", PROVISIONAL, True)
    h.set(H, "v")
    assert _read(tmp_path).backend == "encrypted_file"
    assert (_db(tmp_path).parent / "secrets.enc").exists()
    assert h.get(H) == "v"


def test_record_is_written_before_the_secret(tmp_path):
    class SetRaises(FakeKeyring):
        def set_password(self, service, username, password):
            raise RuntimeError("write failed")

    h = _handle(tmp_path, keyring_backend=SetRaises())
    with pytest.raises(SecretStoreUnavailable):
        h.set(H, "v")
    assert _read(tmp_path).backend == "keyring"
    assert h.get(H) is None


def test_recording_failure_writes_nothing(tmp_path, monkeypatch):
    def boom(self, record):
        raise SecretStoreUnavailable("can't read which store holds your secrets (OperationalError)")

    monkeypatch.setattr(SqliteChoiceStore, "record_if_absent", boom)
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    with pytest.raises(SecretStoreUnavailable):
        h.set(H, "v")
    assert fake.entries == {}
    assert not (_db(tmp_path).parent / "secrets.enc").exists()


def test_pinned_unavailable_store_does_not_fall_back(tmp_path):
    _record(tmp_path, "keyring")
    h = _handle(tmp_path, keyring_backend=_fail_keyring())
    with pytest.raises(SecretStoreUnavailable) as ei:
        h.set(H, "v")
    assert str(ei.value).startswith("secrets are in keyring, which isn't available right now: ")
    with pytest.raises(SecretStoreUnavailable):
        h.get(H)
    assert not (_db(tmp_path).parent / "secrets.enc").exists()
    st = h.status()
    assert st.available is False
    assert st.backend == "keyring"
    assert st.reason == "chosen 2026-11-01 at first save"
    assert st.why_unavailable.startswith("secrets are in keyring")


def test_config_pinned_unavailable_store_does_not_fall_back(tmp_path):
    h = _handle(tmp_path, "keyring", keyring_backend=_fail_keyring())
    with pytest.raises(SecretStoreUnavailable, match="secrets are in keyring"):
        h.set(H, "v")
    assert not (_db(tmp_path).parent / "secrets.enc").exists()
    assert h.status().available is False


def test_unreadable_record_is_unavailable_not_provisional(tmp_path):
    _garbage_db(tmp_path)
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    st = h.status()
    assert st.available is False
    assert st.reason != PROVISIONAL
    assert "can't read which store holds your secrets" in st.why_unavailable
    with pytest.raises(SecretStoreUnavailable):
        h.set(H, "v")
    with pytest.raises(SecretStoreUnavailable):
        h.get(H)
    assert fake.entries == {}


def test_unknown_recorded_backend_is_unavailable(tmp_path):
    _record(tmp_path, "vault")
    h = _handle(tmp_path, keyring_backend=FakeKeyring())
    st = h.status()
    assert st.available is False
    assert st.why_unavailable == "the record names a store Zygos doesn't know: vault"
    with pytest.raises(SecretStoreUnavailable, match="doesn't know: vault"):
        h.get(H)
    with pytest.raises(SecretStoreUnavailable, match="doesn't know: vault"):
        h.set(H, "v")


def _orphaned_enc(tmp_path):
    """A file-store secret whose preferences.db was deleted (personalization reset)."""
    first = _handle(tmp_path, keyring_backend=_fail_keyring())
    first.set(H, "v")
    old_id = _read(tmp_path).install_id
    _db(tmp_path).unlink()
    return old_id


def test_existing_enc_without_record_is_adopted(tmp_path):
    old_id = _orphaned_enc(tmp_path)
    fake = FakeKeyring()
    h = build_secret_store(
        _config(tmp_path), keyring_backend=fake, now=lambda: FIXED_NOW, new_id=lambda: "fresh"
    )
    st = h.status()
    assert (st.backend, st.reason, st.available) == (
        "encrypted_file",
        "found an existing secrets file",
        True,
    )
    assert h.get(H) == "v"
    assert _read(tmp_path) is None  # reads never record
    h.set("provider:other", "w")  # first save records the evidence, not the keychain
    rec = _read(tmp_path)
    assert rec.backend == "encrypted_file"
    assert old_id != "fresh"
    assert rec.install_id == "fresh"  # re-recorded with a new install id
    assert fake.entries == {}
    assert h.get("provider:other") == "w"
    assert h.status().reason == "chosen 2026-11-17 at first save"


def test_reads_on_an_orphaned_enc_never_write(tmp_path):
    _orphaned_enc(tmp_path)
    h = _handle(tmp_path, keyring_backend=FakeKeyring())
    h.status()
    assert h.get(H) == "v"
    assert h.presence(H).state == "set"
    assert h.presence("provider:other").state == "not_set"
    assert not _db(tmp_path).exists()


def test_reads_on_a_fresh_install_never_write(tmp_path):
    h = _handle(tmp_path, keyring_backend=FakeKeyring())
    h.status()
    h.get(H)
    h.presence(H)
    h.delete(H)
    assert not _db(tmp_path).parent.exists()


def _garbage_db(root):
    _db(root).parent.mkdir(parents=True)
    _db(root).write_bytes(b"this is not a sqlite database" * 100)


def test_explicit_file_works_with_an_unreadable_record(tmp_path):
    _garbage_db(tmp_path)
    garbage = _db(tmp_path).read_bytes()
    h = _handle(tmp_path, "encrypted_file", FakeKeyring())
    st = h.status()
    assert (st.backend, st.reason, st.available) == ("encrypted_file", "set in config", True)
    h.set(H, "v")
    assert h.get(H) == "v"
    assert h.presence(H).state == "set"
    assert _db(tmp_path).read_bytes() == garbage  # record ignored, not touched


def test_explicit_keyring_with_an_unreadable_record_is_unavailable(tmp_path):
    _garbage_db(tmp_path)
    fake = FakeKeyring()
    h = _handle(tmp_path, "keyring", fake)
    st = h.status()
    assert (st.backend, st.reason, st.available) == ("keyring", "set in config", False)
    assert "install's id can't be read" in st.why_unavailable
    with pytest.raises(SecretStoreUnavailable, match="install's id can't be read"):
        h.set(H, "v")
    with pytest.raises(SecretStoreUnavailable):
        h.get(H)
    assert fake.entries == {}


def test_explicit_keyring_records_an_install_id_at_first_set(tmp_path):
    fake = FakeKeyring()
    h = _handle(tmp_path, "keyring", fake)
    assert h.get(H) is None
    assert _read(tmp_path) is None
    h.set(H, "v")
    rec = _read(tmp_path)
    assert rec.backend == "keyring"
    assert fake.entries == {(f"zygos:{rec.install_id}", H): "v"}
    assert h.status().location == f"zygos:{rec.install_id}"


def test_loser_follows_recorded_store(tmp_path):
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    assert h.status().backend == "keyring"  # provisional pick
    _record(tmp_path, "encrypted_file", "winner")
    h.set(H, "v")
    assert fake.entries == {}
    assert EncryptedFileStore(_db(tmp_path).parent).get(H) == "v"
    assert _read(tmp_path).install_id == "winner"


def _lose_the_race_to(monkeypatch, winner):
    original = SqliteChoiceStore.record_if_absent

    def racing(self, record):
        original(self, winner)  # another process records first
        return original(self, record)

    monkeypatch.setattr(SqliteChoiceStore, "record_if_absent", racing)


def test_loser_of_a_first_save_race_follows_the_winner(tmp_path, monkeypatch):
    winner = ChoiceRecord(backend="encrypted_file", chosen_at="2026-11-17T00:00:00+00:00", install_id="w")
    _lose_the_race_to(monkeypatch, winner)
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    h.set(H, "v")
    assert fake.entries == {}
    assert EncryptedFileStore(_db(tmp_path).parent).get(H) == "v"
    assert _read(tmp_path) == winner


def test_loser_raises_when_the_winners_store_is_unavailable(tmp_path, monkeypatch):
    winner = ChoiceRecord(backend="keyring", chosen_at="2026-11-17T00:00:00+00:00", install_id="w")
    _lose_the_race_to(monkeypatch, winner)
    h = _handle(tmp_path, keyring_backend=_fail_keyring())
    with pytest.raises(SecretStoreUnavailable, match="secrets are in keyring"):
        h.set(H, "v")
    assert not (_db(tmp_path).parent / "secrets.enc").exists()


def test_presence_set_not_set_unknown(tmp_path):
    h = _handle(tmp_path, keyring_backend=FakeKeyring())
    assert h.presence(H) == Presence("not_set")
    h.set(H, "v")
    assert h.presence(H) == Presence("set")
    assert h.presence("provider:other") == Presence("not_set")
    with pytest.raises(InvalidHandle):
        h.presence("not a handle")

    _record(tmp_path / "b", "vault")
    other = _handle(tmp_path / "b", keyring_backend=FakeKeyring())
    p = other.presence(H)
    assert p.state == "unknown"
    assert "vault" in p.reason
    with pytest.raises(InvalidHandle):
        other.presence("not a handle")


def test_presence_unknown_when_store_raises(tmp_path):
    fake = FakeKeyring()
    h = _handle(tmp_path, keyring_backend=fake)
    h.set(H, "SENTINEL-presence")
    assert h.presence(H).state == "set"

    def locked(service, username):
        raise RuntimeError("locked SENTINEL-presence")

    fake.get_password = locked  # keychain locks mid-session
    p = h.presence(H)
    assert p.state == "unknown"
    assert p.reason and "SENTINEL" not in p.reason


def test_keyring_availability_is_probed_once_per_handle(tmp_path):
    probes = []

    class Counting(FakeKeyring):
        def get_password(self, service, username):
            if username == "zygos-availability-probe":
                probes.append(service)
            return super().get_password(service, username)

    h = _handle(tmp_path, keyring_backend=Counting())
    for _ in range(3):
        h.status()
    h.set(H, "v")
    h.get(H)
    h.presence(H)
    h.status()
    assert len(probes) == 1


def test_file_availability_is_checked_each_call(tmp_path):
    h = _handle(tmp_path, "encrypted_file")
    h.set(H, "v")
    assert h.status().available is True
    (_db(tmp_path).parent / "secrets.key").unlink()
    st = h.status()
    assert st.available is False
    assert "key file missing" in st.why_unavailable


def test_delete(tmp_path):
    h = _handle(tmp_path, keyring_backend=FakeKeyring())
    h.delete(H)  # nothing saved yet: no-op, records nothing
    assert _read(tmp_path) is None
    h.set(H, "v")
    h.delete(H)
    assert h.get(H) is None
    h.delete(H)


def test_no_extra_set_raises_extra_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    h = _handle(tmp_path)
    st = h.status()
    assert st.available is False
    assert st.why_unavailable == EXTRA_MISSING
    with pytest.raises(SecretStoreUnavailable) as ei:
        h.set(H, "v")
    assert str(ei.value) == EXTRA_MISSING
    assert not _db(tmp_path).parent.exists()


def test_two_installs_never_share_keychain_entries(tmp_path):
    fake = FakeKeyring()
    a = _handle(tmp_path / "a", keyring_backend=fake)
    b = build_secret_store(_config(tmp_path / "b"), keyring_backend=fake)
    a.set(H, "va")
    assert b.get(H) is None
    b.set(H, "vb")
    assert a.get(H) == "va"
    assert b.get(H) == "vb"
    assert a.status().location != b.status().location
    assert len(fake.entries) == 2


def test_file_store_accessor(tmp_path):
    h = _handle(tmp_path)
    fs = h.file_store()
    assert isinstance(fs, EncryptedFileStore)
    assert fs.enc_path == _db(tmp_path).parent / "secrets.enc"


def test_build_does_no_io_and_no_optional_imports(tmp_path):
    script = textwrap.dedent(
        f"""
        import os, sys
        from zygos.config.schema import ZygosConfig
        from zygos.secrets import build_secret_store
        cfg = ZygosConfig.model_validate(
            {{"personalization": {{"db_path": {str(_db(tmp_path))!r}}}}}
        )
        build_secret_store(cfg)
        assert "keyring" not in sys.modules, "keyring imported"
        assert "cryptography" not in sys.modules, "cryptography imported"
        assert os.listdir({str(tmp_path)!r}) == [], os.listdir({str(tmp_path)!r})
        """
    )
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": backend_dir},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
