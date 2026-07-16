import dataclasses
import hashlib
from pathlib import Path

import pytest

import zygos.voice.kokoro_assets as ka
from zygos.voice.kokoro_assets import MODEL, VOICES, ensure_assets, resolve_paths, verify_sha256


def test_resolve_paths_defaults_and_override():
    onnx_d, voices_d = resolve_paths(None)
    assert onnx_d == Path(".zygos/models/kokoro") / MODEL.filename
    assert voices_d == Path(".zygos/models/kokoro") / VOICES.filename

    onnx_o, voices_o = resolve_paths("/tmp/models")
    assert onnx_o == Path("/tmp/models") / MODEL.filename
    assert voices_o == Path("/tmp/models") / VOICES.filename


def test_verify_sha256_true_and_false(tmp_path):
    p = tmp_path / "blob.bin"
    p.write_bytes(b"hello kokoro")
    digest = hashlib.sha256(b"hello kokoro").hexdigest()
    assert verify_sha256(p, digest) is True
    assert verify_sha256(p, "0" * 64) is False


def test_ensure_assets_downloads_when_missing(tmp_path, monkeypatch):
    onnx_bytes, voices_bytes = b"ONNX-DATA", b"VOICES-DATA"
    monkeypatch.setattr(ka, "MODEL", dataclasses.replace(ka.MODEL, sha256=hashlib.sha256(onnx_bytes).hexdigest()))
    monkeypatch.setattr(ka, "VOICES", dataclasses.replace(ka.VOICES, sha256=hashlib.sha256(voices_bytes).hexdigest()))

    def fake_urlretrieve(url, dest):
        Path(dest).write_bytes(onnx_bytes if url == ka.MODEL.url else voices_bytes)

    monkeypatch.setattr(ka.urllib.request, "urlretrieve", fake_urlretrieve)

    onnx_path, voices_path = ensure_assets(str(tmp_path))
    assert onnx_path.read_bytes() == onnx_bytes
    assert voices_path.read_bytes() == voices_bytes


def test_ensure_assets_skips_when_present_and_valid(tmp_path, monkeypatch):
    onnx_path, voices_path = ka.resolve_paths(str(tmp_path))
    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    onnx_path.write_bytes(b"CACHED-ONNX")
    voices_path.write_bytes(b"CACHED-VOICES")
    monkeypatch.setattr(ka, "MODEL", dataclasses.replace(ka.MODEL, sha256=hashlib.sha256(b"CACHED-ONNX").hexdigest()))
    monkeypatch.setattr(ka, "VOICES", dataclasses.replace(ka.VOICES, sha256=hashlib.sha256(b"CACHED-VOICES").hexdigest()))

    def boom(url, dest):
        raise AssertionError("should not download when cache is valid")

    monkeypatch.setattr(ka.urllib.request, "urlretrieve", boom)
    ensure_assets(str(tmp_path))  # must not raise


def test_ensure_assets_rejects_sha_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(ka, "MODEL", dataclasses.replace(ka.MODEL, sha256="0" * 64))
    monkeypatch.setattr(ka, "VOICES", dataclasses.replace(ka.VOICES, sha256="0" * 64))
    monkeypatch.setattr(ka.urllib.request, "urlretrieve",
                        lambda url, dest: Path(dest).write_bytes(b"WRONG"))
    with pytest.raises(RuntimeError, match="sha256 mismatch"):
        ensure_assets(str(tmp_path))
    # Verify temp files are cleaned up after mismatch
    assert not list(tmp_path.rglob("*.part"))
