"""Test-side GGUF writer (little-endian, v2/v3)."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any


def s(text: str) -> bytes:
    b = text.encode()
    return struct.pack("<Q", len(b)) + b


def value(kind: int, v: Any) -> bytes:
    fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 10: "<Q", 11: "<q", 12: "<d"}
    if kind in fmt:
        return struct.pack(fmt[kind], v)
    if kind == 7:
        return struct.pack("<B", 1 if v else 0)
    if kind == 8:
        return s(v)
    if kind == 9:
        item_kind, items = v
        return struct.pack("<IQ", item_kind, len(items)) + b"".join(value(item_kind, i) for i in items)
    raise ValueError(kind)


def kv(key: str, kind: int, v: Any) -> bytes:
    return s(key) + struct.pack("<I", kind) + value(kind, v)


def write_gguf(
    path: Path,
    kvs: list[tuple[str, int, Any]],
    tensors: list[tuple[str, list[int], int, int]] | None = None,
    *,
    version: int = 3,
    data_size: int = 256,
    alignment: int = 32,
) -> Path:
    """tensors: (name, dims, ggml_type, offset)."""
    tensors = tensors or []
    out = b"GGUF" + struct.pack("<IQQ", version, len(tensors), len(kvs))
    out += b"".join(kv(*e) for e in kvs)
    for name, dims, gtype, off in tensors:
        out += s(name) + struct.pack("<I", len(dims)) + b"".join(struct.pack("<Q", d) for d in dims)
        out += struct.pack("<IQ", gtype, off)
    pad = (-len(out)) % alignment
    out += b"\0" * pad + b"\0" * data_size
    path.write_bytes(out)
    return path
