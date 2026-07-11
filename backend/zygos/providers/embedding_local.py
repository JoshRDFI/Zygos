"""In-process CPU embedder (fastembed/ONNX) — the RFC-0006 default embedder.

CPU-bound encoding is offloaded via asyncio.to_thread so it never blocks the
single event loop (RFC-0002). fastembed is imported lazily so this module loads
without the `embeddings` optional extra installed.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from zygos.providers.types import EmbedRequest, EmbedResult, Usage
from zygos.runtime.capabilities import Capability

DEFAULT_LOCAL_MODEL = "BAAI/bge-small-en-v1.5"


class LocalEmbedder:
    name = "local"
    capabilities: frozenset[Capability] = frozenset({Capability.EMBEDDING})

    def __init__(self, *, model: str = DEFAULT_LOCAL_MODEL) -> None:
        from fastembed import TextEmbedding  # lazy: only when constructed

        self._model_name = model
        self._model = TextEmbedding(model_name=model)

    def _encode(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return tuple(tuple(float(x) for x in vec) for vec in self._model.embed(list(texts)))

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        vectors = await asyncio.to_thread(self._encode, request.texts)
        dim = len(vectors[0]) if vectors else 0
        return EmbedResult(vectors=vectors, model=self._model_name, dim=dim, usage=Usage())
