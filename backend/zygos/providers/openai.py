"""OpenAI-protocol provider — chat completions, SSE streaming.

Stability: Experimental. See RFC-0001 section on provider stability.
"""

import json
from typing import AsyncIterator

import httpx

from zygos.errors import ProviderProtocolError
from zygos.providers.base import (
    DEFAULT_CLOUD_MAX_TOKENS,
    ProviderSettings,
    ensure_ok,
    translate_transport_error,
)
from zygos.providers.types import (
    EmbedRequest, EmbedResult, GenerationChunk, GenerationRequest, GenerationResult, Usage,
)
from zygos.runtime.capabilities import Capability


class OpenAIProvider:
    name = "openai"
    capabilities: frozenset[Capability] = frozenset({Capability.LOCAL_INFERENCE, Capability.EMBEDDING})
    chat_path = "/chat/completions"
    embeddings_path = "/embeddings"
    # ADR-0006: cloud default cap when the request carries none. Subclasses for local
    # backends (vLLM) override to None so local inference stays uncapped.
    default_max_tokens: int | None = DEFAULT_CLOUD_MAX_TOKENS

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        if self._settings.api_key:
            return {"Authorization": f"Bearer {self._settings.api_key}"}
        return {}

    def _body(self, request: GenerationRequest, stream: bool) -> dict:
        body: dict = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "temperature": request.temperature,
            "stream": stream,
        }
        cap = request.max_tokens if request.max_tokens is not None else self.default_max_tokens
        if cap is not None:
            body["max_tokens"] = cap
        return body

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            response = await self._client.post(
                f"{self._settings.base_url}{self.chat_path}",
                json=self._body(request, stream=False),
                headers=self._headers(),
                timeout=self._settings.timeout_s,
            )
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
        ensure_ok(self.name, response)
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderProtocolError(f"{self.name} returned malformed body: {error}", provider=self.name) from error
        usage = payload.get("usage") or {}
        return GenerationResult(
            text=text,
            model=request.model,
            provider=self.name,
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
        )

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        try:
            response = await self._client.post(
                f"{self._settings.base_url}{self.embeddings_path}",
                json={"model": request.model, "input": list(request.texts)},
                headers=self._headers(),
                timeout=self._settings.timeout_s,
            )
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
        ensure_ok(self.name, response)
        try:
            payload = response.json()
            rows = sorted(payload["data"], key=lambda d: d["index"])
            vectors = tuple(tuple(float(x) for x in row["embedding"]) for row in rows)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            raise ProviderProtocolError(
                f"{self.name} returned malformed embeddings body: {error}", provider=self.name
            ) from error
        dim = len(vectors[0]) if vectors else 0
        usage = payload.get("usage") or {}
        return EmbedResult(
            vectors=vectors, model=payload.get("model", request.model), dim=dim,
            usage=Usage(input_tokens=usage.get("prompt_tokens", 0)),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        try:
            async with self._client.stream(
                "POST",
                f"{self._settings.base_url}{self.chat_path}",
                json=self._body(request, stream=True),
                headers=self._headers(),
                timeout=self._settings.timeout_s,
            ) as response:
                ensure_ok(self.name, response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        yield GenerationChunk(text="", done=True)
                        return
                    try:
                        payload = json.loads(data)
                    except ValueError as error:
                        raise ProviderProtocolError(f"{self.name} sent malformed SSE: {error}", provider=self.name) from error
                    delta = payload.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield GenerationChunk(text=content)
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
