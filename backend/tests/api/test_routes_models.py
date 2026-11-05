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
    assert set(body) == {"hardware", "ollama", "models", "default"}
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
    # only configured routes; Ollama ones say why they have no fit
    assert all(not m["loaded"] for m in body["models"])
    assert [m["fit_text"] for m in body["models"] if m["provider"] == "ollama"] == ["Ollama unreachable"] * len(
        [m for m in body["models"] if m["provider"] == "ollama"])


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


@pytest.mark.asyncio
async def test_get_models_with_unwritable_profiles_dir_is_200(tmp_path):
    import os

    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, 0o555)
    try:
        original, runtime = _runtime(root)
        try:
            async with _client(_mount(runtime)) as client:
                resp = await client.get("/models")
        finally:
            await original.aclose()
    finally:
        os.chmod(root, 0o755)
    assert resp.status_code == 200
    qwen = next(m for m in resp.json()["models"] if m["name"] == "qwen3:8b" and m["loaded"] is False
                and m["fit"] is not None)
    assert qwen["profile_error"].startswith("profile can't be saved: ")


# -- PUT/DELETE /models/default (RFC-0013 §4, §10) ------------------------------


class _Residency:
    def __init__(self):
        self.preloads = []

    def preload(self, route):
        self.preloads.append(route)


class _MultiOllama(_Ollama):
    def __init__(self, models):
        super().__init__()
        self._models = models

    async def list_models(self):
        return self._models

    async def show(self, model):
        from zygos.providers.types import OllamaShow

        return OllamaShow(capabilities=("completion",), parameters="num_ctx 8192", model_info={
            "general.architecture": "qwen3", "general.parameter_count": 8_000_000_000,
            "qwen3.block_count": 36, "qwen3.attention.head_count_kv": 8,
            "qwen3.attention.key_length": 128, "qwen3.context_length": 40960})


_MODELS = (
    OllamaModel(name="qwen3:8b", size=5 * 1024**3, digest="d1", family="qwen3"),
    OllamaModel(name="mistral:latest", size=4 * 1024**3, digest="d4", family="mistral"),
    OllamaModel(name="gemma4:e4b", size=3 * 1024**3, digest="d2", family="gemma4"),
    OllamaModel(name="huge:405b", size=400 * 1024**3, digest="d3", family="huge"),
)


def _picker(tmp_path, residency=None):
    from zygos.models.choices import SqliteModelChoicesStore
    from zygos.models.default import resolve_default
    from zygos.services.router import RouteChoice

    runtime = build_runtime()
    store = SqliteModelChoicesStore(tmp_path / "p.db")
    primary = RouteChoice(runtime.config.providers.primary.provider,
                          runtime.config.providers.primary.model)
    holder = []

    def status():
        return resolve_default(store.get(), primary, installed=holder[0].installed,
                               routable=lambda name: name == "ollama")

    catalog = ModelCatalog(providers={"ollama": _MultiOllama(_MODELS)}, profiles=ProfileStore(tmp_path / "prof"),
                           hardware=_probe([]), config=runtime.config, voice_snapshot=lambda: None,
                           clock=lambda: NOW, default_status=status)
    holder.append(catalog)
    res = residency if residency is not None else _Residency()
    return runtime, replace(runtime, model_choices=store, default_status=status,
                            model_catalog=catalog, residency=res), res


async def _put(runtime, body):
    async with _client(_mount(runtime)) as client:
        return await client.put("/models/default", json=body)


@pytest.mark.asyncio
async def test_put_default_saves_and_marks_entry(tmp_path):
    original, runtime, res = _picker(tmp_path)
    try:
        resp = await _put(runtime, {"provider": "ollama", "model": "gemma4:e4b"})
        async with _client(_mount(runtime)) as client:
            again = (await client.get("/models")).json()
    finally:
        await original.aclose()
    assert resp.status_code == 200
    for body in (resp.json(), again):
        assert body["default"]["source"] == "saved"
        assert body["default"]["route"] == {"provider": "ollama", "model": "gemma4:e4b"}
        assert [m["name"] for m in body["models"] if m["is_default"]] == ["gemma4:e4b"]
    assert [(r.provider, r.model) for r in res.preloads] == [("ollama", "gemma4:e4b")]


@pytest.mark.asyncio
async def test_no_saved_default_marks_config_primary(tmp_path):
    original, runtime, _ = _picker(tmp_path)
    try:
        async with _client(_mount(runtime)) as client:
            body = (await client.get("/models")).json()
    finally:
        await original.aclose()
    assert body["default"]["source"] == "config"
    assert [m["name"] for m in body["models"] if m["is_default"]] == ["qwen3:8b"]


@pytest.mark.asyncio
async def test_put_untagged_ollama_name_matches_latest_listing(tmp_path):
    original, runtime, res = _picker(tmp_path)
    try:
        resp = await _put(runtime, {"provider": "ollama", "model": "mistral"})
    finally:
        await original.aclose()
    assert resp.status_code == 200
    assert runtime.model_choices.get().default_model.model == "mistral:latest"
    assert [m["name"] for m in resp.json()["models"] if m["is_default"]] == ["mistral:latest"]
    assert [r.model for r in res.preloads] == ["mistral:latest"]


@pytest.mark.asyncio
async def test_put_unknown_model_404_and_nothing_saved(tmp_path):
    original, runtime, res = _picker(tmp_path)
    try:
        resp = await _put(runtime, {"provider": "ollama", "model": "nope:1b"})
        saved = runtime.model_choices.get().default_model
    finally:
        await original.aclose()
    assert resp.status_code == 404
    assert resp.json() == {"detail": "ollama/nope:1b isn't listed"}
    assert saved is None and res.preloads == []


@pytest.mark.asyncio
async def test_put_llamacpp_409_exact_text(tmp_path):
    from zygos.models.catalog import ModelEntry

    original, runtime, res = _picker(tmp_path)
    real_view = runtime.model_catalog.view

    async def view(ctx):
        v = await real_view(ctx)
        first = v.models[0]
        extra = first.model_copy(update={"provider": "llamacpp", "name": "Llama-3.gguf"})
        return v.model_copy(update={"models": (*v.models, extra)})

    runtime.model_catalog.view = view  # type: ignore[method-assign]
    try:
        resp = await _put(runtime, {"provider": "llamacpp", "model": "Llama-3.gguf", "confirm": True})
    finally:
        await original.aclose()
    assert resp.status_code == 409
    assert resp.json() == {
        "detail": "llama.cpp models can't answer yet — Zygos starts llama-server in a later phase"}
    assert runtime.model_choices.get().default_model is None and res.preloads == []


@pytest.mark.asyncio
async def test_put_fit_no_needs_confirm_then_saves(tmp_path):
    original, runtime, res = _picker(tmp_path)
    try:
        first = await _put(runtime, {"provider": "ollama", "model": "huge:405b"})
        after_refusal = runtime.model_choices.get().default_model
        second = await _put(runtime, {"provider": "ollama", "model": "huge:405b", "confirm": True})
    finally:
        await original.aclose()
    assert first.status_code == 409
    body = first.json()
    assert body["needs_confirm"] is True and body["fit"] in {"no", "unknown"}
    assert body["detail"] and after_refusal is None
    assert second.status_code == 200
    assert second.json()["default"]["source"] == "saved"
    assert len(res.preloads) == 1


@pytest.mark.asyncio
async def test_delete_default_restores_config_and_is_noop_when_unset(tmp_path):
    original, runtime, _ = _picker(tmp_path)
    try:
        await _put(runtime, {"provider": "ollama", "model": "gemma4:e4b"})
        async with _client(_mount(runtime)) as client:
            resp = await client.delete("/models/default")
            noop = await client.delete("/models/default")
    finally:
        await original.aclose()
    for r in (resp, noop):
        assert r.status_code == 200
        assert r.json()["default"]["source"] == "config"
        assert [m["name"] for m in r.json()["models"] if m["is_default"]] == ["qwen3:8b"]
    assert runtime.model_choices.get().default_model is None


@pytest.mark.asyncio
async def test_put_and_delete_never_write_the_config_file(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("providers:\n  primary: {provider: ollama, model: 'qwen3:8b'}\n")
    before = cfg.read_bytes()
    original, runtime, _ = _picker(tmp_path)
    try:
        await _put(runtime, {"provider": "ollama", "model": "gemma4:e4b"})
        async with _client(_mount(runtime)) as client:
            await client.delete("/models/default")
    finally:
        await original.aclose()
    assert cfg.read_bytes() == before


@pytest.mark.asyncio
async def test_saved_default_survives_restart(tmp_path):
    from zygos.models.choices import SqliteModelChoicesStore

    original, runtime, _ = _picker(tmp_path)
    try:
        await _put(runtime, {"provider": "ollama", "model": "gemma4:e4b"})
    finally:
        await original.aclose()
    original2, runtime2, _ = _picker(tmp_path)  # a new runtime on the same db
    try:
        async with _client(_mount(runtime2)) as client:
            body = (await client.get("/models")).json()
    finally:
        await original2.aclose()
    assert body["default"]["source"] == "saved"
    assert [m["name"] for m in body["models"] if m["is_default"]] == ["gemma4:e4b"]


@pytest.mark.asyncio
async def test_saved_default_not_installed_is_ignored_and_reported(tmp_path):
    from zygos.models.choices import DefaultModel, ModelChoices

    original, runtime, _ = _picker(tmp_path)
    runtime.model_choices.set(ModelChoices(default_model=DefaultModel(provider="ollama", model="gone:7b")))
    try:
        async with _client(_mount(runtime)) as client:
            body = (await client.get("/models")).json()
    finally:
        await original.aclose()
    assert body["default"]["source"] == "config"
    assert body["default"]["ignored"] == {"provider": "ollama", "model": "gone:7b"}
    assert body["default"]["reason"] == "not installed"
    assert [m["name"] for m in body["models"] if m["is_default"]] == ["qwen3:8b"]
