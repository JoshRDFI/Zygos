import httpx

from zygos.providers.anthropic import AnthropicProvider
from zygos.providers.base import ProviderSettings
from zygos.providers.fake import FakeProvider
from zygos.providers.ollama import OllamaProvider
from zygos.providers.openai import OpenAIProvider
from zygos.providers.vllm import VllmProvider


def _client():
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))


def test_every_provider_declares_native_tool_support():
    s = ProviderSettings(base_url="http://x")
    providers = [
        FakeProvider(),
        OpenAIProvider(settings=s, client=_client()),
        VllmProvider(settings=s, client=_client()),
        OllamaProvider(settings=s, client=_client()),
        AnthropicProvider(settings=s, client=_client()),
    ]
    for p in providers:
        assert p.supports_native_tools is True
