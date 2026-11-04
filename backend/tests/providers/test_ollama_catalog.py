import json

import httpx
import pytest

from zygos.errors import ProviderProtocolError, ProviderUnavailable
from zygos.providers.base import ProviderSettings
from zygos.providers.ollama import OllamaProvider

from .conftest import make_client

SETTINGS = ProviderSettings(base_url="http://localhost:11434")
DIGEST = "500a1f067a9f" + "0" * 52

QWEN = {
    "name": "qwen3:8b", "model": "qwen3:8b", "size": 5225388164, "digest": DIGEST,
    "details": {"format": "gguf", "family": "qwen3", "families": ["qwen3"],
                "parameter_size": "8.2B", "quantization_level": "Q4_K_M",
                "context_length": 40960, "embedding_length": 4096},
    "capabilities": ["completion", "tools", "thinking"],
}
GEMMA = {
    "name": "gemma4:latest", "model": "gemma4:latest", "size": 9000000000, "digest": "ab" * 32,
    "details": {"format": "gguf", "family": "gemma4", "parameter_size": "8B",
                "quantization_level": "Q4_K_M"},
    "capabilities": ["completion"],
}


def _make(handler) -> OllamaProvider:
    return OllamaProvider(settings=SETTINGS, client=make_client(handler))


def _json(payload):
    return lambda request: httpx.Response(200, json=payload)


async def test_list_models_flattens_details():
    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [QWEN]})

    (m,) = await _make(handler).list_models()
    assert (m.name, m.size, m.digest) == ("qwen3:8b", 5225388164, DIGEST)
    assert (m.family, m.parameter_size, m.quantization_level) == ("qwen3", "8.2B", "Q4_K_M")
    assert m.context_length == 40960
    assert m.capabilities == ("completion", "tools", "thinking")


async def test_list_models_tolerates_missing_context_length():
    (m,) = await _make(_json({"models": [GEMMA]})).list_models()
    assert m.context_length is None
    assert m.family == "gemma4"


async def test_running_models_reads_size_vram_and_context_length():
    ps = {"models": [{"name": "qwen3:8b", "model": "qwen3:8b", "size": 6000000000, "digest": DIGEST,
                      "details": {}, "expires_at": "2026-11-04T00:00:00Z",
                      "size_vram": 5900000000, "context_length": 4096}]}

    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/ps"
        return httpx.Response(200, json=ps)

    (r,) = await _make(handler).running_models()
    assert (r.name, r.digest, r.size) == ("qwen3:8b", DIGEST, 6000000000)
    assert r.size_vram == 5900000000
    assert r.context_length == 4096


async def test_show_returns_model_info_and_parameters():
    def handler(request):
        assert request.url.path == "/api/show"
        assert json.loads(request.content) == {"model": "qwen3:8b"}
        return httpx.Response(200, json={
            "capabilities": ["completion", "thinking"], "details": {"family": "qwen3"},
            "model_info": {"qwen3.block_count": 36}, "parameters": "num_ctx 4096",
            "license": "x", "modelfile": "FROM x", "template": "t", "tensors": []})

    s = await _make(handler).show("qwen3:8b")
    assert s.capabilities == ("completion", "thinking")
    assert s.model_info == {"qwen3.block_count": 36}
    assert s.parameters == "num_ctx 4096"
    assert s.details == {"family": "qwen3"}


CALLS = [
    ("list_models", ()), ("running_models", ()), ("show", ("qwen3:8b",)),
]


@pytest.mark.parametrize("method,args", CALLS)
async def test_catalog_calls_translate_transport_errors(method, args):
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailable):
        await getattr(_make(handler), method)(*args)


@pytest.mark.parametrize("method,args", CALLS)
async def test_catalog_calls_reject_malformed_body(method, args):
    def handler(request):
        return httpx.Response(200, content=b"not json")

    with pytest.raises(ProviderProtocolError):
        await getattr(_make(handler), method)(*args)


@pytest.mark.parametrize("method,args", CALLS)
async def test_catalog_calls_reject_wrong_shape(method, args):
    with pytest.raises(ProviderProtocolError):
        await getattr(_make(_json({"models": [{"nope": 1}]} if method != "show" else [1])), method)(*args)


async def test_list_models_null_capabilities_parse_to_default():
    entry = {**QWEN, "capabilities": None, "details": None}
    m, gemma = await _make(_json({"models": [entry, GEMMA]})).list_models()
    assert m.capabilities == () and m.family is None
    assert gemma.capabilities == ("completion",)  # one bad entry does not fail the read


async def test_show_null_fields_parse_to_defaults():
    payload = {"capabilities": None, "model_info": None, "details": None, "parameters": None}
    s = await _make(_json(payload)).show("qwen3:8b")
    assert s.capabilities == () and s.model_info == {} and s.details == {} and s.parameters is None
