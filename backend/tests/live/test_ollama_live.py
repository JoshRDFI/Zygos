"""Opt-in live smoke test against a real local Ollama (pytest -m live).

Auto-discovers an installed model: ZYGOS_LIVE_MODEL env var wins; otherwise
the first non-embedding model from /api/tags. Never assumes a specific model.
"""

import os

import httpx
import pytest

from zygos.providers.base import ProviderSettings
from zygos.providers.ollama import OllamaProvider
from zygos.providers.types import GenerationRequest, Message

pytestmark = pytest.mark.live

BASE_URL = os.environ.get("ZYGOS_LIVE_OLLAMA_URL", "http://localhost:11434")


async def _discover_model() -> str:
    override = os.environ.get("ZYGOS_LIVE_MODEL")
    if override:
        return override
    async with httpx.AsyncClient() as probe:
        try:
            response = await probe.get(f"{BASE_URL}/api/tags", timeout=5.0)
            response.raise_for_status()
        except httpx.HTTPError:
            pytest.skip(f"Ollama not reachable at {BASE_URL}")
    models = [m["name"] for m in response.json().get("models", []) if "embed" not in m["name"]]
    if not models:
        pytest.skip("No non-embedding model installed in Ollama")
    return models[0]


async def test_live_generate_and_stream():
    model = await _discover_model()
    async with httpx.AsyncClient() as client:
        provider = OllamaProvider(settings=ProviderSettings(base_url=BASE_URL), client=client)
        request = GenerationRequest(
            model=model,
            messages=(Message(role="user", content="Reply with one short word."),),
            max_tokens=16,
            temperature=0.0,
        )
        result = await provider.generate(request)
        assert result.text.strip()
        assert result.usage.output_tokens >= 0

        chunks = [c async for c in provider.stream(request)]
        assert chunks[-1].done is True
        assert any(c.text for c in chunks[:-1])
