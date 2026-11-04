"""GET /models and GET /hardware (RFC-0013 §1-§3, §11)."""

from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import FastAPI

from zygos.api.routes_models import router
from zygos.errors import ProviderUnavailable
from zygos.hardware.probe import HardwareProbe
from zygos.models.catalog import ModelCatalog
from zygos.models.store import ProfileStore
from zygos.providers.types import OllamaModel
from zygos.runtime.bootstrap import build_runtime

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)


class _Ollama:
    name = "ollama"
    capabilities = frozenset()

    def __init__(self, fail=False):
        self.fail = fail

    async def list_models(self):
        if self.fail:
            raise ProviderUnavailable("connection refused", provider="ollama")
        return (OllamaModel(name="qwen3:8b", size=5 * 1024**3, digest="d1", family="qwen3"),)

    async def running_models(self):
        if self.fail:
            raise ProviderUnavailable("connection refused", provider="ollama")
        return ()

    async def show(self, model):
        raise ProviderUnavailable("no show", provider="ollama")


def _probe(calls):
    def smi():
        calls.append(1)
        return "RTX, 16303, 12000\n"
    return HardwareProbe(run_nvidia_smi=smi, read_text=lambda p: None, disk_free=lambda p: 0,
                         cpu_count=lambda: 8, env={}, exists=lambda p: False, clock=lambda: NOW)


def _runtime(tmp_path, *, fail=False, calls=None):
    runtime = build_runtime()
    probe = _probe(calls if calls is not None else [])
    store = ProfileStore(tmp_path)
    catalog = ModelCatalog(providers={"ollama": _Ollama(fail)}, profiles=store, hardware=probe,
                           config=runtime.config, voice_snapshot=lambda: None, clock=lambda: NOW)
    return runtime, replace(runtime, hardware=probe, profiles=store, model_catalog=catalog)


def _mount(runtime):
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_get_models(tmp_path):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(_mount(runtime)) as client:
            resp = await client.get("/models")
    finally:
        await original.aclose()
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"hardware", "ollama", "models"}
    assert body["ollama"] == {"configured": True, "reachable": True, "error": None}
    entry = body["models"][0]
    assert entry["name"] == "qwen3:8b" and entry["location"] == "local"
    assert {"provider", "fit", "fit_text", "fields", "primary", "fallback", "profile_error",
            "loaded", "vram_bytes", "capabilities", "specialty"} <= set(entry)
    assert entry["fit"]["level"] in {"gpu", "partial", "no", "unknown"}
    assert entry["fields"]["identity.family"]["source"] == "ollama"


@pytest.mark.asyncio
async def test_get_models_ollama_unreachable_is_200(tmp_path):
    original, runtime = _runtime(tmp_path, fail=True)
    try:
        async with _client(_mount(runtime)) as client:
            resp = await client.get("/models")
    finally:
        await original.aclose()
    assert resp.status_code == 200
    body = resp.json()
    assert body["ollama"]["reachable"] is False
    assert "connection refused" in body["ollama"]["error"]
    assert body["models"] == []


@pytest.mark.asyncio
async def test_get_hardware_rescans(tmp_path):
    calls = []
    original, runtime = _runtime(tmp_path, calls=calls)
    try:
        async with _client(_mount(runtime)) as client:
            resp = await client.get("/hardware")
    finally:
        await original.aclose()
    assert resp.status_code == 200
    assert calls == [1]
    body = resp.json()
    assert body["gpus"][0]["vram_free_bytes"] == 12000 * 1024**2
    assert {"ram_total_bytes", "cpu_cores", "disk_free_bytes", "scanned_at"} <= set(body)
