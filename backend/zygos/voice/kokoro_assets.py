"""Pinned Kokoro-ONNX model + voices assets, and first-run provisioning.

ONE place to bump the pinned version. On a software update, the update path must
re-verify these and refresh to a newer pinned version if appropriate (ties into
check-for-updates, Archon 8494c00c). Fetch-on-first-run, sha256-verified; never
bundled. Quantized (int8) model by default (~89 MB).

Stability: Experimental.
"""
from __future__ import annotations

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
