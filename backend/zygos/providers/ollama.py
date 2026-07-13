"""Ollama provider — native /api/chat, NDJSON streaming (RFC-0001 §2).

Stability: Experimental.
"""

import json
from typing import AsyncIterator

import httpx

from zygos.errors import ProviderProtocolError
from zygos.providers.base import ProviderSettings, ensure_ok, translate_transport_error
from zygos.providers.types import (
    EmbedRequest, EmbedResult, GenerationChunk, GenerationRequest, GenerationResult, Usage,
)
from zygos.runtime.capabilities import Capability


class OllamaProvider:
    name = "ollama"
    supports_native_tools = True
    capabilities: frozenset[Capability] = frozenset(
        {Capability.LOCAL_INFERENCE, Capability.EMBEDDING}
    )

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _body(self, request: GenerationRequest, stream: bool) -> dict:
        options: dict = {"temperature": request.temperature}
        # ADR-0006: local inference is uncapped unless the caller sets an explicit
        # cap. Omitting num_predict lets the model generate to its natural stop.
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        return {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": stream,
            "options": options,
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            response = await self._client.post(
                f"{self._settings.base_url}/api/chat",
                json=self._body(request, stream=False),
                timeout=self._settings.timeout_s,
            )
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
        ensure_ok(self.name, response)
        try:
            payload = response.json()
            text = payload["message"]["content"]
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderProtocolError(f"ollama returned malformed body: {error}", provider=self.name) from error
        return GenerationResult(
            text=text,
            model=request.model,
            provider=self.name,
            usage=Usage(
                input_tokens=payload.get("prompt_eval_count", 0),
                output_tokens=payload.get("eval_count", 0),
            ),
        )

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        try:
            response = await self._client.post(
                f"{self._settings.base_url}/api/embed",
                json={"model": request.model, "input": list(request.texts)},
                timeout=self._settings.timeout_s,
            )
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
        ensure_ok(self.name, response)
        try:
            payload = response.json()
            vectors = tuple(tuple(float(x) for x in v) for v in payload["embeddings"])
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderProtocolError(
                f"ollama returned malformed embeddings body: {error}", provider=self.name
            ) from error
        dim = len(vectors[0]) if vectors else 0
        return EmbedResult(
            vectors=vectors, model=payload.get("model", request.model), dim=dim, usage=Usage()
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        try:
            async with self._client.stream(
                "POST",
                f"{self._settings.base_url}/api/chat",
                json=self._body(request, stream=True),
                timeout=self._settings.timeout_s,
            ) as response:
                ensure_ok(self.name, response)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError as error:
                        raise ProviderProtocolError(f"ollama sent malformed NDJSON: {error}", provider=self.name) from error
                    if payload.get("done"):
                        yield GenerationChunk(text="", done=True)
                        return
                    yield GenerationChunk(text=payload.get("message", {}).get("content", ""))
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
