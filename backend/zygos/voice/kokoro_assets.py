"""Pinned Kokoro-ONNX model + voices assets, and first-run provisioning.

ONE place to bump the pinned version. On a software update, the update path must
re-verify these and refresh to a newer pinned version if appropriate (ties into
check-for-updates, Archon 8494c00c). Fetch-on-first-run, sha256-verified; never
bundled. Quantized (int8) model by default (~89 MB).

Stability: Experimental.
"""
from __future__ import annotations

import hashlib
import urllib.request
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DOWNLOAD_ROOT = ".zygos/models/kokoro"


@dataclass(frozen=True)
class Asset:
    filename: str
    url: str
    sha256: str


# --- PINNED (bump here on update; re-verify sha256) --------------------------
PINNED_VERSION = "model-files-v1.0"
MODEL = Asset(
    filename="kokoro-v1.0.int8.onnx",
    url="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
    sha256="6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
)
VOICES = Asset(
    filename="voices-v1.0.bin",
    url="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
    sha256="bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
)
# ----------------------------------------------------------------------------


def resolve_paths(download_root: str | None) -> tuple[Path, Path]:
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT)
    return root / MODEL.filename, root / VOICES.filename


def verify_sha256(path: Path, expected: str) -> bool:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest() == expected


def _download(asset: Asset, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        urllib.request.urlretrieve(asset.url, tmp)
        if not verify_sha256(tmp, asset.sha256):
            raise RuntimeError(f"sha256 mismatch for {asset.filename}")
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def ensure_assets(download_root: str | None) -> tuple[Path, Path]:
    onnx_path, voices_path = resolve_paths(download_root)
    for asset, path in ((MODEL, onnx_path), (VOICES, voices_path)):
        if not (path.exists() and verify_sha256(path, asset.sha256)):
            _download(asset, path)
    return onnx_path, voices_path
