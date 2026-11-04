"""GET/PUT /backends (RFC-0014 section 2, 10)."""

import httpx
import pytest
from fastapi import FastAPI

from zygos.api.routes_backends import router
from zygos.backends.settings import BackendsSettings, OllamaBackend, VllmEndpoint
from zygos.backends.store import SqliteBackendsStore
from zygos.runtime.bootstrap import build_runtime


def _runtime(tmp_path, **kw):
    from dataclasses import replace
    runtime = build_runtime()
    store = SqliteBackendsStore(tmp_path / "p.db")
    return runtime, replace(runtime, backends=store, **kw)


def _client(runtime):
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


@pytest.mark.asyncio
async def test_get_nothing_set_up(tmp_path):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            body = (await c.get("/backends")).json()
    finally:
        await original.aclose()
    assert body["vllm"] is None and body["restart_required"] is False
    assert body["llamacpp"]["server"]["ok"] is False
    assert body["llamacpp"]["models"]["ok"] is False
    assert body["settings"]["llamacpp"]["default_args"] == ""
    assert "ok" in body["ollama"]
    assert body["address_sources"]["ollama"] == "default"


@pytest.mark.asyncio
async def test_put_valid_saves_and_returns(tmp_path):
    original, runtime = _runtime(tmp_path)
    payload = {"llamacpp": {"default_args": "-c 8192", "model_args": {"a.gguf": "-ngl 20"}}}
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json=payload)
    finally:
        await original.aclose()
    assert resp.status_code == 200
    assert resp.json()["settings"]["llamacpp"]["default_args"] == "-c 8192"
    assert runtime.backends.get().llamacpp.model_args == {"a.gguf": "-ngl 20"}


@pytest.mark.asyncio
async def test_put_refuses_zygos_flag_naming_field(tmp_path):
    original, runtime = _runtime(tmp_path)
    payload = {"llamacpp": {"default_args": "-c 1", "model_args": {"m.gguf": "--port=1"}}}
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json=payload)
    finally:
        await original.aclose()
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"detail", "field"}
    assert body["field"] == "llamacpp.model_args.m.gguf" and "--port" in body["detail"]
    assert runtime.backends.get() == BackendsSettings()


@pytest.mark.asyncio
async def test_put_unbalanced_quote_names_default_args(tmp_path):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json={"llamacpp": {"default_args": "--x 'oops"}})
    finally:
        await original.aclose()
    assert resp.status_code == 422 and resp.json()["field"] == "llamacpp.default_args"


@pytest.mark.asyncio
async def test_restart_required_after_ollama_address_change(tmp_path):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            before = (await c.get("/backends")).json()["restart_required"]
            resp = await c.put("/backends", json={"ollama": {"base_url": "http://other:1"}})
    finally:
        await original.aclose()
    assert before is False and resp.json()["restart_required"] is True


@pytest.mark.asyncio
async def test_no_restart_when_record_matches_start(tmp_path):
    original, runtime = _runtime(tmp_path, addresses_at_start={"ollama": "http://other:1"})
    runtime.backends.set(BackendsSettings(ollama=OllamaBackend(base_url="http://other:1")))
    try:
        async with _client(runtime) as c:
            body = (await c.get("/backends")).json()
    finally:
        await original.aclose()
    assert body["restart_required"] is False


@pytest.mark.asyncio
async def test_vllm_down_is_reported_not_fatal(tmp_path):
    original, runtime = _runtime(tmp_path)
    runtime.backends.set(BackendsSettings(vllm=[VllmEndpoint(base_url="http://127.0.0.1:1/v1")]))
    try:
        async with _client(runtime) as c:
            resp = await c.get("/backends")
    finally:
        await original.aclose()
    body = resp.json()
    assert resp.status_code == 200
    assert body["vllm"]["check"]["ok"] is False and body["vllm"]["served"] == []
