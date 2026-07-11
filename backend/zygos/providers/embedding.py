"""Embedder contract — a provider-tier contract peer to Provider (RFC-0006 §1).

Separate from Provider on purpose: not every backend can embed (Anthropic cannot),
and a pure embedding backend need not be a chat provider.

Stability: Experimental.
"""

from typing import Protocol, runtime_checkable

from zygos.providers.types import EmbedRequest, EmbedResult


@runtime_checkable
class Embedder(Protocol):
    name: str

    async def embed(self, request: EmbedRequest) -> EmbedResult: ...
