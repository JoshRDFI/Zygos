"""GET/PUT /backends (RFC-0014 section 2, 10)."""

import httpx
import pytest
from fastapi import FastAPI

from zygos.api.routes_backends import router
from zygos.backends.settings import BackendsSettings, OllamaBackend, VllmEndpoint
from zygos.backends.store import SqliteBackendsStore
from zygos.runtime.bootstrap import build_runtime


START = {"ollama": "http://localhost:11434", "vllm": "http://localhost:8000/v1"}


def _runtime(tmp_path, **kw):
    """Hermetic: the startup addresses are given, not read from this machine's record."""
    from dataclasses import replace
    runtime = build_runtime()
    store = SqliteBackendsStore(tmp_path / "p.db")
    kw.setdefault("addresses_at_start", dict(START))
    kw.setdefault("address_sources", {"ollama": "default", "vllm": "default"})
    return runtime, replace(runtime, backends=store, **kw)


def _config(**providers):
    from zygos.config.schema import ZygosConfig
    return ZygosConfig.model_validate({"providers": providers})


def _recording(answer):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return answer(request)

    return calls, httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _answer(request):
    if request.url.path.endswith("/api/version"):
        return httpx.Response(200, json={"version": "0.9.1"})
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "qwen"}]})
    return httpx.Response(404)


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
    payload = {"llamacpp": {"default_args": "-c 8192", "model_args": {"Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M": "-ngl 20"}}}
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json=payload)
    finally:
        await original.aclose()
    assert resp.status_code == 200
    assert resp.json()["settings"]["llamacpp"]["default_args"] == "-c 8192"
    assert runtime.backends.get().llamacpp.model_args == {"Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M": "-ngl 20"}


@pytest.mark.asyncio
async def test_put_refuses_zygos_flag_naming_field(tmp_path):
    original, runtime = _runtime(tmp_path)
    payload = {"llamacpp": {"default_args": "-c 1", "model_args": {"gemma/gemma-3-4b": "--port=1"}}}
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json=payload)
    finally:
        await original.aclose()
    assert resp.status_code == 422
    body = resp.json()
    assert set(body) == {"detail", "field"}
    assert body["field"] == "llamacpp.model_args.gemma/gemma-3-4b" and "--port" in body["detail"]
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
    original, runtime = _runtime(tmp_path, addresses_at_start={**START, "ollama": "http://other:1"})
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


@pytest.mark.asyncio
async def test_unrouted_unrecorded_ollama_is_not_set_up_and_not_probed(tmp_path):
    calls, client = _recording(_answer)
    original, runtime = _runtime(
        tmp_path, http_client=client, config=_config(primary={"provider": "fake", "model": "f"}))
    try:
        async with _client(runtime) as c:
            body = (await c.get("/backends")).json()
    finally:
        await client.aclose()
        await original.aclose()
    assert body["ollama"] is None
    assert not any("/api/version" in u for u in calls)


@pytest.mark.asyncio
async def test_config_only_ollama_address_is_shown_and_probed(tmp_path):
    calls, client = _recording(_answer)
    config = _config(primary={"provider": "ollama", "model": "q"},
                     credentials={"ollama": {"base_url": "http://cfg:1"}})
    original, runtime = _runtime(
        tmp_path, http_client=client, config=config,
        addresses_at_start={**START, "ollama": "http://cfg:1"},
        address_sources={"ollama": "config", "vllm": "default"})
    try:
        async with _client(runtime) as c:
            body = (await c.get("/backends")).json()
    finally:
        await client.aclose()
        await original.aclose()
    assert calls == ["http://cfg:1/api/version"]
    assert body["ollama"] == {"ok": True, "detail": "Ollama 0.9.1 at http://cfg:1"}
    assert body["restart_required"] is False


@pytest.mark.asyncio
async def test_config_only_vllm_route_is_checked(tmp_path):
    calls, client = _recording(_answer)
    config = _config(primary={"provider": "fake", "model": "f"},
                     fallbacks=[{"provider": "vllm", "model": "qwen"}],
                     credentials={"vllm": {"base_url": "http://cfgv:2/v1"}})
    original, runtime = _runtime(tmp_path, http_client=client, config=config,
                                 addresses_at_start={**START, "vllm": "http://cfgv:2/v1"})
    try:
        async with _client(runtime) as c:
            body = (await c.get("/backends")).json()
    finally:
        await client.aclose()
        await original.aclose()
    assert "http://cfgv:2/v1/models" in calls
    assert body["vllm"]["served"] == ["qwen"]


@pytest.mark.asyncio
async def test_clearing_a_recorded_address_via_put_requires_restart(tmp_path):
    original, runtime = _runtime(tmp_path, addresses_at_start={**START, "ollama": "http://rec:2"})
    runtime.backends.set(BackendsSettings(ollama=OllamaBackend(base_url="http://rec:2")))
    try:
        async with _client(runtime) as c:
            before = (await c.get("/backends")).json()["restart_required"]
            after = (await c.put("/backends", json={})).json()["restart_required"]
    finally:
        await original.aclose()
    assert before is False and after is True


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, field", [
    ({"ollama": {"base_url": "box:11434"}}, "ollama.base_url"),
    ({"ollama": {"base_url": "ftp://box"}}, "ollama.base_url"),
    ({"vllm": [{"name": "vllm", "base_url": "localhost:8000/v1"}]}, "vllm.base_url"),
])
async def test_put_refuses_an_address_without_http_scheme(tmp_path, payload, field):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json=payload)
    finally:
        await original.aclose()
    assert resp.status_code == 422
    assert resp.json() == {"detail": f"{field} must be an http:// or https:// address", "field": field}
    assert runtime.backends.get() == BackendsSettings()


@pytest.mark.asyncio
async def test_put_accepts_https_address(tmp_path):
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json={"ollama": {"base_url": "https://box:11434"}})
    finally:
        await original.aclose()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_put_expands_and_absolutises_paths(tmp_path, monkeypatch):
    home = tmp_path / "home"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "llama-server"
    exe.write_text("#!/bin/sh\necho 'version: 1'\n")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.chdir(tmp_path)
    original, runtime = _runtime(tmp_path)
    try:
        async with _client(runtime) as c:
            resp = await c.put("/backends", json={
                "llamacpp": {"server_path": "llama-server", "models_dir": "~/gguf"}})
            rel = await c.put("/backends", json={
                "llamacpp": {"server_path": "~/llama.cpp/llama-server", "models_dir": "models/gguf"}})
            missing = await c.put("/backends", json={"llamacpp": {"server_path": "no-such-server"}})
    finally:
        await original.aclose()
    assert resp.status_code == 200
    assert resp.json()["settings"]["llamacpp"] == {
        "server_path": str(exe), "models_dir": str(home / "gguf"),
        "default_args": "", "model_args": {}}
    saved = rel.json()["settings"]["llamacpp"]
    assert saved["server_path"] == str(home / "llama.cpp" / "llama-server")
    assert saved["models_dir"] == str(tmp_path / "models" / "gguf")
    body = missing.json()
    assert body["settings"]["llamacpp"]["server_path"] == "no-such-server"
    assert body["llamacpp"]["server"]["ok"] is False
    assert runtime.backends.get().llamacpp.server_path == "no-such-server"
