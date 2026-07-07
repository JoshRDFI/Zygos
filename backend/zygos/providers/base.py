"""Provider contract and shared HTTP error mapping (RFC-0001 §2).

Stability: Experimental.
"""

from typing import AsyncIterator, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict

from zygos.errors import (
    ProviderAuthFailed,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult

DEFAULT_BASE_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "vllm": "http://localhost:8000/v1",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "fake": "http://fake.invalid",
}

# ADR-0006: generous default cap for cloud providers when a request carries no
# explicit max_tokens. Model token appetite rises over time, so this is a floor
# to revisit (a config hook is a tracked follow-up), never a starving constant.
DEFAULT_CLOUD_MAX_TOKENS = 4096


class ProviderSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    api_key: str | None = None
    # ADR-0006: with token caps lifted for local inference, the request timeout is
    # the backstop against a runaway/looping generation — generous enough for long
    # thinking, finite enough to kill a wedged call.
    timeout_s: float = 300.0


@runtime_checkable
class Provider(Protocol):
    name: str

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...


def ensure_ok(provider: str, response: httpx.Response) -> None:
    if response.status_code in (401, 403):
        raise ProviderAuthFailed(f"{provider} rejected credentials ({response.status_code})", provider=provider)
    if response.status_code == 429:
        raise ProviderRateLimited(f"{provider} rate limited the request", provider=provider)
    if response.status_code >= 500:
        raise ProviderUnavailable(f"{provider} returned {response.status_code}", provider=provider)
    if response.status_code >= 400:
        raise ProviderProtocolError(f"{provider} returned {response.status_code}", provider=provider)


def translate_transport_error(provider: str, error: Exception) -> ProviderError:
    if isinstance(error, httpx.TimeoutException):
        return ProviderTimeout(f"{provider} timed out: {error}", provider=provider)
    if isinstance(error, httpx.TransportError):
        return ProviderUnavailable(f"{provider} unreachable: {error}", provider=provider)
    return ProviderProtocolError(f"{provider} protocol failure: {error}", provider=provider)
