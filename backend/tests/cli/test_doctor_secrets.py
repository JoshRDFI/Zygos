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
