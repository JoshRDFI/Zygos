"""A sentinel value must never appear in logs, errors, reprs, doctor, manifest or db."""

import asyncio
import logging

import pytest

pytest.importorskip("keyring")
pytest.importorskip("cryptography")

from secret_store.fakes import FakeKeyring, RaisingKeyring, backend_in  # noqa: E402
from zygos.cli.doctor import run_doctor  # noqa: E402
from zygos.runtime.bootstrap import build_runtime  # noqa: E402
from zygos.runtime.manifest import runtime_manifest  # noqa: E402
from zygos.secrets import SecretStoreError, build_secret_store  # noqa: E402
from zygos.config.schema import ZygosConfig  # noqa: E402

SENTINEL = "SENTINEL-4c1d"
H = "provider:anthropic"


def _cfg_text(root, backend):
    return (
        f"personalization:\n  db_path: '{root / '.zygos' / 'preferences.db'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
        f"secrets:\n  backend: {backend}\n"
    )


def _doctor_text(report):
    return "\n".join(f"{c.name} {c.ok} {c.detail}" for c in report.checks)


def test_sentinel_never_leaks(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    seen: list[str] = []

    def note(exc):
        seen.append(str(exc))
        seen.append(repr(exc))
        import traceback

        seen.append("".join(traceback.format_exception(exc)))

    cfg = tmp_path / "config.yaml"
    cfg.write_text(_cfg_text(tmp_path, "encrypted_file"))

    async def go():
        runtime = build_runtime(cfg)
        try:
            runtime.secrets.set(H, SENTINEL)
            fs = runtime.secrets.file_store()
            good = fs.enc_path.read_bytes()
            # tamper -> get
            bad = bytearray(good)
            bad[-1] ^= 1
            fs.enc_path.write_bytes(bytes(bad))
            with pytest.raises(SecretStoreError) as e:
                runtime.secrets.get(H)
            note(e.value)
            with pytest.raises(SecretStoreError) as e:
                runtime.secrets.set(H, SENTINEL)  # never overwrites a corrupt file
            note(e.value)
            fs.enc_path.write_bytes(good)
            # remove key -> get
            key = fs.key_path.read_bytes()
            fs.key_path.unlink()
            with pytest.raises(SecretStoreError) as e:
                runtime.secrets.get(H)
            note(e.value)
            with pytest.raises(SecretStoreError) as e:
                runtime.secrets.set(H, SENTINEL)
            note(e.value)
            fs.key_path.write_bytes(key)
            fs.key_path.chmod(0o600)
            report = await run_doctor(runtime, gpu_query=lambda: None)
            manifest = runtime_manifest(runtime).model_dump_json()
            reprs = [repr(runtime.secrets), repr(fs)]
            return _doctor_text(report), manifest, reprs
        finally:
            await runtime.aclose()

    doctor, manifest, reprs = asyncio.run(go())

    # raising keyring -> presence / unavailable pinned store -> set
    kroot = tmp_path / "k"
    kcfg = ZygosConfig.model_validate(
        {"personalization": {"db_path": str(kroot / ".zygos" / "preferences.db")},
         "secrets": {"backend": "keyring"}}
    )
    h = build_secret_store(kcfg, keyring_backend=RaisingKeyring())
    presence = h.presence(H)
    seen.append(repr(presence))
    with pytest.raises(SecretStoreError) as e:
        h.set(H, SENTINEL)
    note(e.value)
    reprs.append(repr(h))
    # recording failure: choice db path is a directory
    rroot = tmp_path / "r"
    (rroot / ".zygos" / "preferences.db").mkdir(parents=True)
    rcfg = ZygosConfig.model_validate(
        {"personalization": {"db_path": str(rroot / ".zygos" / "preferences.db")},
         "secrets": {"backend": "auto"}}
    )
    hr = build_secret_store(rcfg, keyring_backend=FakeKeyring())
    with pytest.raises(SecretStoreError) as e:
        hr.set(H, SENTINEL)
    note(e.value)
    # unavailable pinned store: fail-module keyring
    uroot = tmp_path / "u"
    ucfg = ZygosConfig.model_validate(
        {"personalization": {"db_path": str(uroot / ".zygos" / "preferences.db")},
         "secrets": {"backend": "keyring"}}
    )
    hu = build_secret_store(ucfg, keyring_backend=backend_in("keyring.backends.fail"))
    with pytest.raises(SecretStoreError) as e:
        hu.set(H, SENTINEL)
    note(e.value)

    db_bytes = b"".join(p.read_bytes() for p in tmp_path.rglob("preferences.db") if p.is_file())
    haystack = [caplog.text, doctor, manifest, *reprs, *seen]
    for text in haystack:
        assert SENTINEL not in text
    assert SENTINEL.encode() not in db_bytes
    assert any("integrity" in s for s in seen)  # the error paths really fired
