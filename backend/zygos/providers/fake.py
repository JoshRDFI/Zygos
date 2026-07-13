"""Deterministic in-memory provider for tests and zero-dependency demos.

Stability: Experimental.
"""

import hashlib
from typing import AsyncIterator

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.types import (
    EmbedRequest, EmbedResult, GenerationChunk, GenerationRequest, GenerationResult, Usage,
)
from zygos.runtime.capabilities import Capability


class FakeProvider:
    name = "fake"
    supports_native_tools = True
    capabilities: frozenset[Capability] = frozenset({Capability.LOCAL_INFERENCE})

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        script: list["str | Exception | GenerationResult"] | None = None,
        text: str = "fake response",
    ) -> None:
        self._script = list(script) if script is not None else None
        self._text = text

    def _next_item(self):
        if self._script is None:
            return self._text
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        item = self._next_item()
        if isinstance(item, GenerationResult):
            return item
        text = item
        return GenerationResult(
            text=text, model=request.model, provider=self.name,
            usage=Usage(input_tokens=len(request.messages), output_tokens=len(text.split())),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        item = self._next_item()
        text = item.text if isinstance(item, GenerationResult) else item
        for word in text.split():
            yield GenerationChunk(text=word)
        yield GenerationChunk(text="", done=True)


class FakeEmbedder:
    """Deterministic embedder for tests: same text -> same vector, fixed dim."""

    name = "fake"
    capabilities: frozenset[Capability] = frozenset({Capability.EMBEDDING})

    def __init__(self, *, dim: int = 8, model: str = "fake-embed") -> None:
        self._dim = dim
        self._model = model

    def _vector(self, text: str) -> tuple[float, ...]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return tuple(digest[i % len(digest)] / 255.0 for i in range(self._dim))

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        vectors = tuple(self._vector(t) for t in request.texts)
        return EmbedResult(vectors=vectors, model=self._model, dim=self._dim, usage=Usage())
