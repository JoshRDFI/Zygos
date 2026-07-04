"""Anthropic provider — /v1/messages, SSE event streaming.

Stability: Experimental (RFC-0001).
"""

import json
from typing import AsyncIterator

import httpx

from zygos.errors import ProviderProtocolError
from zygos.providers.base import ProviderSettings, ensure_ok, translate_transport_error
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Usage

_API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"anthropic-version": _API_VERSION}
        if self._settings.api_key:
            headers["x-api-key"] = self._settings.api_key
        return headers

    def _body(self, request: GenerationRequest, stream: bool) -> dict:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        body: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [
                {"role": m.role, "content": m.content} for m in request.messages if m.role != "system"
            ],
            "stream": stream,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        return body

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            response = await self._client.post(
                f"{self._settings.base_url}/v1/messages",
                json=self._body(request, stream=False),
                headers=self._headers(),
                timeout=self._settings.timeout_s,
            )
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
        ensure_ok(self.name, response)
        try:
            payload = response.json()
            text = payload["content"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderProtocolError(f"anthropic returned malformed body: {error}", provider=self.name) from error
        usage = payload.get("usage") or {}
        return GenerationResult(
            text=text,
            model=request.model,
            provider=self.name,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
        )

    async def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]:
        try:
            async with self._client.stream(
                "POST",
                f"{self._settings.base_url}/v1/messages",
                json=self._body(request, stream=True),
                headers=self._headers(),
                timeout=self._settings.timeout_s,
            ) as response:
                ensure_ok(self.name, response)
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    try:
                        payload = json.loads(line[len("data:"):].strip())
                    except ValueError as error:
                        raise ProviderProtocolError(f"anthropic sent malformed SSE: {error}", provider=self.name) from error
                    kind = payload.get("type")
                    if kind == "content_block_delta":
                        text = payload.get("delta", {}).get("text", "")
                        if text:
                            yield GenerationChunk(text=text)
                    elif kind == "message_stop":
                        yield GenerationChunk(text="", done=True)
                        return
        except httpx.HTTPError as error:
            raise translate_transport_error(self.name, error) from error
