import asyncio
import sys

import pytest

from secret_store.fakes import FakeKeyring
from zygos.cli.doctor import run_doctor
from zygos.runtime.bootstrap import build_runtime
from zygos.secrets import EXTRA_MISSING


def _write(tmp_path, backend=None):
    cfg = tmp_path / "config.yaml"
    db = tmp_path / ".zygos" / "preferences.db"
    extra = f"secrets:\n  backend: {backend}\n" if backend else ""
    cfg.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n" + extra
    )
    return cfg


def _report(cfg, before=None):
    async def go():
        runtime = build_runtime(cfg)
        try:
            if before:
                before(runtime)
            return await run_doctor(runtime, gpu_query=lambda: None), runtime
        finally:
            await runtime.aclose()

    return asyncio.run(go())


def _check(report, name="secrets"):
    return {c.name: c for c in report.checks}.get(name)


def test_doctor_secrets_provisional_ok(tmp_path, monkeypatch):
    pytest.importorskip("keyring")
    from zygos.secrets import resolve

    cfg = _write(tmp_path)
    # keychain usable via injected fake: patch the builder default
    real = resolve.build_secret_store
    monkeypatch.setattr(
        "zygos.runtime.bootstrap.build_secret_store",
        lambda c: real(c, keyring_backend=FakeKeyring()),
    )
    report, _ = _report(cfg)
    c = _check(report)
    assert c.ok and not c.warn
    assert c.detail == "keyring (provisional — nothing saved yet)"


def test_doctor_secrets_pinned_file_shows_location(tmp_path):
    pytest.importorskip("cryptography")
    cfg = _write(tmp_path, "encrypted_file")
    report, runtime = _report(cfg, before=lambda r: r.secrets.set("provider:x", "v"))
    c = _check(report)
    assert c.ok and not c.warn
    assert c.detail == (
        f"encrypted_file (set in config) — {tmp_path / '.zygos' / 'secrets.enc'}"
    )


def test_doctor_secrets_extra_missing_is_warn_and_report_ok(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    report, _ = _report(_write(tmp_path))
    c = _check(report)
    assert c.ok and c.warn
    assert c.detail == f"not available — {EXTRA_MISSING}"
    assert report.ok


def test_doctor_explicit_store_missing_extra_nothing_saved_is_warn(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cryptography", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers", None)
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    report, _ = _report(_write(tmp_path, "encrypted_file"))
    c = _check(report)
    assert c.ok and c.warn
    assert c.detail.startswith("not available — ")
    assert report.ok


def test_doctor_secrets_recorded_store_unavailable_fails(tmp_path):
    from datetime import datetime, timezone

    from zygos.secrets.choice import ChoiceRecord, SqliteChoiceStore

    cfg = _write(tmp_path)
    SqliteChoiceStore(tmp_path / ".zygos" / "preferences.db").record_if_absent(
        ChoiceRecord(backend="keyring", chosen_at=datetime.now(timezone.utc).isoformat(),
                     install_id="abc")
    )
    report, _ = _report(cfg)  # autouse guard: keychain is the fail backend
    c = _check(report)
    assert not c.ok and not report.ok
    assert "keyring" in c.detail and "isn't available" in c.detail


def test_doctor_secrets_corrupt_file_fails(tmp_path):
    pytest.importorskip("cryptography")
    cfg = _write(tmp_path, "encrypted_file")

    def seed(r):
        r.secrets.set("provider:x", "v")
        p = r.secrets.file_store().enc_path
        b = bytearray(p.read_bytes())
        b[-1] ^= 1
        p.write_bytes(bytes(b))

    report, _ = _report(cfg, before=seed)
    c = _check(report)
    assert not c.ok
    assert c.detail == "secrets file failed its integrity check"


def test_doctor_secrets_loose_key_warns(tmp_path):
    pytest.importorskip("cryptography")
    cfg = _write(tmp_path, "encrypted_file")

    def seed(r):
        r.secrets.set("provider:x", "v")
        r.secrets.file_store().key_path.chmod(0o644)

    report, runtime = _report(cfg, before=seed)
    k = _check(report, "secrets_key_file")
    key = tmp_path / ".zygos" / "secrets.key"
    assert k.ok and k.warn
    assert k.detail == f"{key} is readable by other users; run chmod 600 {key}"


def test_doctor_never_writes_secrets(tmp_path):
    cfg = _write(tmp_path)
    _report(cfg)
    z = tmp_path / ".zygos"
    assert not (z / "secrets.enc").exists()
    assert not (z / "secrets.key").exists()
    from zygos.secrets.choice import SqliteChoiceStore

    assert SqliteChoiceStore(z / "preferences.db").read() is None


def test_doctor_completes_when_keyring_discovery_raises(tmp_path, monkeypatch):
    keyring = pytest.importorskip("keyring")

    def boom():
        raise ModuleNotFoundError("nonexistent.mod")

    monkeypatch.setattr(keyring, "get_keyring", boom)
    report, _ = _report(_write(tmp_path))
    assert _check(report) is not None


def test_doctor_unexpected_secrets_error_is_a_fail_line(tmp_path):
    def broken(runtime):
        def status():
            raise RuntimeError("boom SENTINEL-99")

        runtime.secrets.status = status

    report, _ = _report(_write(tmp_path), before=broken)
    c = _check(report)
    assert not c.ok
    assert c.detail == "unexpected error (RuntimeError)"
    assert _check(report, "default_model") is not None  # the report went on


def _garbage_record(tmp_path):
    import sqlite3

    db = tmp_path / ".zygos" / "preferences.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE secrets_backend (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    con.execute("INSERT INTO secrets_backend VALUES (1, 'not json')")
    con.commit()
    con.close()


def test_doctor_explicit_file_ignores_unreadable_record_nothing_saved_is_warn(tmp_path, monkeypatch):
    # Explicit encrypted_file ignores the record, so "saved" is the file only.
    monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.ciphers.aead", None)
    _garbage_record(tmp_path)
    report, _ = _report(_write(tmp_path, "encrypted_file"))
    c = _check(report)
    assert c.ok and c.warn


def test_doctor_missing_key_with_file_present_fails(tmp_path):
    pytest.importorskip("cryptography")

    def seed(r):
        r.secrets.set("provider:x", "v")
        r.secrets.file_store().key_path.unlink()

    report, _ = _report(_write(tmp_path, "encrypted_file"), before=seed)
    c = _check(report)
    assert not c.ok
    assert "key file missing" in c.detail


def test_doctor_tight_key_has_no_key_file_line(tmp_path):
    pytest.importorskip("cryptography")
    report, _ = _report(
        _write(tmp_path, "encrypted_file"), before=lambda r: r.secrets.set("provider:x", "v")
    )
    assert _check(report, "secrets_key_file") is None


def test_doctor_does_not_read_the_record_itself(tmp_path, monkeypatch):
    # The "saved" question goes through the handle (one read), not a second SqliteChoiceStore.
    import zygos.secrets.choice as choice

    made = []
    real_init = choice.SqliteChoiceStore.__init__

    def spy(self, path):
        made.append(path)
        real_init(self, path)

    monkeypatch.setattr(choice.SqliteChoiceStore, "__init__", spy)
    _report(_write(tmp_path))
    assert len(made) == 1  # the handle's own, built at build_runtime


def test_doctor_stuck_line_names_when_the_store_was_chosen(tmp_path):
    from zygos.secrets.choice import ChoiceRecord, SqliteChoiceStore

    cfg = _write(tmp_path)
    SqliteChoiceStore(tmp_path / ".zygos" / "preferences.db").record_if_absent(
        ChoiceRecord(backend="keyring", chosen_at="2026-11-20T09:00:00+00:00", install_id="abc")
    )
    report, _ = _report(cfg)
    assert _check(report).detail.startswith(
        "secrets are in keyring (chosen 2026-11-20 at first save), which isn't available right now: "
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_doctor_unstattable_secrets_file_is_a_named_fail(tmp_path, monkeypatch):
    import pathlib

    cfg = _write(tmp_path, "encrypted_file")
    real_exists = pathlib.Path.exists

    def exists(self, *a, **k):
        if self.name == "secrets.enc":
            raise PermissionError(13, "denied")
        return real_exists(self, *a, **k)

    def seed(r):
        monkeypatch.setattr(pathlib.Path, "exists", exists)

    report, _ = _report(cfg, before=seed)
    c = _check(report)
    assert not c.ok
    assert "unexpected error" not in c.detail
    assert "secrets.enc" in c.detail
