"""GGUF header reader (RFC-0014 §3). Reads only the header; never tensor data."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel

MAGIC = b"GGUF"
SUPPORTED_VERSIONS = (2, 3)
ARRAY_KEEP_LIMIT = 64
DEFAULT_ALIGNMENT = 32
MAX_STRING_BYTES = 16 * 1024**2  # one metadata string; real headers stay far below

# type id -> (name, struct format, size)
_FIXED: dict[int, tuple[str, str, int]] = {
    0: ("uint8", "<B", 1),
    1: ("int8", "<b", 1),
    2: ("uint16", "<H", 2),
    3: ("int16", "<h", 2),
    4: ("uint32", "<I", 4),
    5: ("int32", "<i", 4),
    6: ("float32", "<f", 4),
    7: ("bool", "<B", 1),
    10: ("uint64", "<Q", 8),
    11: ("int64", "<q", 8),
    12: ("float64", "<d", 8),
}
_STRING = 8
_ARRAY = 9
_MAX_DEPTH = 8


class GgufError(ValueError):
    """The file is not a readable GGUF header."""


class GgufTensor(BaseModel):
    name: str
    offset: int
    size_bytes: int


class GgufHeader(BaseModel):
    version: int
    metadata: dict[str, Any]
    tensors: tuple[GgufTensor, ...]
    data_offset: int
    file_size: int


class _Reader:
    def __init__(self, f: BinaryIO, size: int) -> None:
        self.f = f
        self.size = size

    def remaining(self) -> int:
        return self.size - self.f.tell()

    def take(self, n: int) -> bytes:
        if n < 0 or n > self.remaining():
            raise GgufError("file is truncated")
        data = self.f.read(n)
        if len(data) != n:
            raise GgufError("file is truncated")
        return data

    def skip(self, n: int) -> None:
        if n < 0 or n > self.remaining():
            raise GgufError("file is truncated")
        self.f.seek(n, 1)

    def unpack(self, fmt: str, size: int) -> Any:
        return struct.unpack(fmt, self.take(size))[0]

    def u32(self) -> int:
        return self.unpack("<I", 4)

    def u64(self) -> int:
        return self.unpack("<Q", 8)

    def string(self) -> str:
        n = self.u64()
        if n > MAX_STRING_BYTES:
            raise GgufError("metadata string too long")
        if n > self.remaining():
            raise GgufError("string length runs past end of file")
        return self.take(n).decode("utf-8", errors="replace")

    def skip_string(self) -> None:
        n = self.u64()
        if n > self.remaining():
            raise GgufError("string length runs past end of file")
        self.skip(n)


def _value(r: _Reader, kind: int, depth: int = 0) -> Any:
    if kind in _FIXED:
        _, fmt, size = _FIXED[kind]
        v = r.unpack(fmt, size)
        return bool(v) if kind == 7 else v
    if kind == _STRING:
        return r.string()
    if kind == _ARRAY:
        if depth >= _MAX_DEPTH:
            raise GgufError("arrays nested too deeply")
        item = r.u32()
        count = r.u64()
        if item != _ARRAY and item != _STRING and item not in _FIXED:
            raise GgufError(f"unknown array item type {item}")
        if item in _FIXED:
            if count * _FIXED[item][2] > r.remaining():
                raise GgufError("array runs past end of file")
        elif count > r.remaining():  # every string/array item takes >= 8 bytes
            raise GgufError("array runs past end of file")
        if count > ARRAY_KEEP_LIMIT:
            if item in _FIXED:
                r.skip(count * _FIXED[item][2])
            else:
                for _ in range(count):
                    if item == _STRING:
                        r.skip_string()
                    else:
                        _value(r, item, depth + 1)
            name = "string" if item == _STRING else "array" if item == _ARRAY else _FIXED[item][0]
            return {"type": name, "length": count}
        return [_value(r, item, depth + 1) for _ in range(count)]
    raise GgufError(f"unknown metadata value type {kind}")


def read_header(path: Path) -> GgufHeader:
    try:
        with open(path, "rb") as f:
            return _read(f, path.stat().st_size)
    except OSError as exc:
        raise GgufError(f"cannot open file: {exc.strerror or exc}") from exc
    except struct.error as exc:  # defensive; take() checks sizes first
        raise GgufError("file is truncated") from exc


def _read(f: BinaryIO, size: int) -> GgufHeader:
    r = _Reader(f, size)
    if r.take(4) != MAGIC:
        raise GgufError("bad magic (not a GGUF file)")
    version = r.u32()
    if version not in SUPPORTED_VERSIONS:
        raise GgufError(f"unsupported GGUF version {version}")
    tensor_count = r.u64()
    kv_count = r.u64()
    # Each kv takes >= 12 bytes, each tensor info >= 24.
    if kv_count * 12 > r.remaining():
        raise GgufError("metadata count runs past end of file")
    if tensor_count * 24 > r.remaining():
        raise GgufError("tensor count runs past end of file")

    metadata: dict[str, Any] = {}
    for _ in range(kv_count):
        key = r.string()
        kind = r.u32()
        metadata[key] = _value(r, kind)

    raw: list[tuple[str, int]] = []
    for _ in range(tensor_count):
        name = r.string()
        n_dims = r.u32()
        if n_dims * 8 > r.remaining():
            raise GgufError("tensor dimensions run past end of file")
        r.skip(n_dims * 8)
        r.u32()  # ggml type
        raw.append((name, r.u64()))

    alignment = metadata.get("general.alignment", DEFAULT_ALIGNMENT)
    if not isinstance(alignment, int) or isinstance(alignment, bool) or alignment <= 0:
        alignment = DEFAULT_ALIGNMENT
    end = f.tell()
    data_offset = -(-end // alignment) * alignment
    if data_offset > size:
        raise GgufError("file is truncated")

    raw.sort(key=lambda t: t[1])
    data_size = size - data_offset
    if any(off >= data_size for _name, off in raw):  # download cut inside the tensor data
        raise GgufError("file is truncated")
    tensors = []
    for i, (name, off) in enumerate(raw):
        nxt = raw[i + 1][1] if i + 1 < len(raw) else data_size
        tensors.append(GgufTensor(name=name, offset=off, size_bytes=max(nxt - off, 0)))
    return GgufHeader(
        version=version,
        metadata=metadata,
        tensors=tuple(tensors),
        data_offset=data_offset,
        file_size=size,
    )
