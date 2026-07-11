"""Vector serialization + cosine similarity (RFC-0006 §3).

Vectors persist as little-endian float32 BLOBs. Pure stdlib (no numpy) so the
primitive and its tests run without the `embeddings` extra.

Stability: Experimental.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence


def pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
