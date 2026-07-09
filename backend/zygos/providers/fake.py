"""Deterministic in-memory provider for tests and zero-dependency demos.

Stability: Experimental.
"""

from typing import AsyncIterator

import httpx

from zygos.providers.base import ProviderSettings
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Usage
from zygos.runtime.capabilities import Capability


class FakeProvider:
    name = "fake"
    capabilities: frozenset[Capability] = frozenset({Capability.LOCAL_INFERENCE})

    def __init__(
        self,
        settings: ProviderSettings | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        script: list[str | Exception] | None = None,
        text: str = "fake response",
    ) -> None:
        self._script = list(script) if script is not None else None
        self._text = text

    def _next_text(self) -> str:
        if self._script is None:
            return self._text
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        text = self._next_text()
        return GenerationResult(
            text=text,
            model=request.model,
            provider=self.name,
            usage=Usage(input_tokens=len(request.messages), output_tokens=len(text.split())),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        text = self._next_text()
        for word in text.split():
            yield GenerationChunk(text=word)
        yield GenerationChunk(text="", done=True)
