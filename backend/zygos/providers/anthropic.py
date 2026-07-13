"""Anthropic provider — /v1/messages, SSE event streaming.

Stability: Experimental (RFC-0001).
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
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    ToolInvocation,
    Usage,
)
from zygos.runtime.capabilities import Capability

_API_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"
    supports_native_tools = True
    capabilities: frozenset[Capability] = frozenset({Capability.LOCAL_INFERENCE})

    def __init__(self, settings: ProviderSettings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        headers = {"anthropic-version": _API_VERSION}
        if self._settings.api_key:
            headers["x-api-key"] = self._settings.api_key
        return headers

    def _content_blocks(self, m) -> list[dict]:
        blocks: list[dict] = []
        if m.content:
            blocks.append({"type": "text", "text": m.content})
        for tc in m.tool_calls:
            blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments})
        return blocks

    def _messages(self, request: GenerationRequest) -> list[dict]:
        out: list[dict] = []
        for m in request.messages:
            if m.role == "system":
                continue
            if m.role == "assistant" and m.tool_calls:
                out.append({"role": "assistant", "content": self._content_blocks(m)})
            elif m.role == "tool":
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": m.tool_call_id, "content": m.content}]})
            else:
                out.append({"role": m.role, "content": m.content})
        return out

    @staticmethod
    def _tool_choice(request: GenerationRequest) -> dict:
        return {"none": {"type": "auto"}, "auto": {"type": "auto"}, "required": {"type": "any"}}[request.tool_choice]

    def _body(self, request: GenerationRequest, stream: bool) -> dict:
        system_parts = [m.content for m in request.messages if m.role == "system"]
        # ADR-0006: anthropic requires max_tokens; fall back to the generous cloud
        # default when the caller gives none.
        max_tokens = request.max_tokens if request.max_tokens is not None else DEFAULT_CLOUD_MAX_TOKENS
        body: dict = {
            "model": request.model,
            "max_tokens": max_tokens,
            "temperature": request.temperature,
            "messages": self._messages(request),
            "stream": stream,
        }
        if system_parts:
            body["system"] = "\n".join(system_parts)
        # Anthropic has no explicit "none" tool_choice; the honest mapping for a
        # caller that says "none" (RFC-0008 loop final degrade) is to simply not
        # advertise any tools at all.
        if request.tools and request.tool_choice != "none":
            body["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters}
                             for t in request.tools]
            body["tool_choice"] = self._tool_choice(request)
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
            text_parts, tool_calls = [], []
            for block in payload["content"]:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls.append(ToolInvocation(id=block["id"], name=block["name"],
                                                     arguments=block.get("input", {})))
            text = "".join(text_parts)
            finish_reason = self._finish_reason(payload.get("stop_reason"))
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
            tool_calls=tuple(tool_calls),
            finish_reason=finish_reason,
        )

    @staticmethod
    def _finish_reason(raw: str | None) -> str:
        return {"tool_use": "tool_calls", "max_tokens": "length",
                "end_turn": "stop", "stop_sequence": "stop"}.get(raw, "stop")

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
