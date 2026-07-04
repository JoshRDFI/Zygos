"""OpenAI-protocol provider — chat completions, SSE streaming.

Stability: Experimental. See RFC-0001 section on provider stability.
"""

import json
from typing import AsyncIterator

import httpx

from zygos.errors import ProviderProtocolError
from zygos.providers.base import ProviderSettings, ensure_ok, translate_transport_error
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Usage


class OpenAIProvider:
    name = "openai"
    chat_path = "/chat/completions"

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        if self._settings.api_key:
            return {"Authorization": f"Bearer {self._settings.api_key}"}
        return {}

    def _body(self, request: GenerationRequest, stream: bool) -> dict:
        return {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": stream,
        }

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
