import httpx
import pytest
from fastapi import FastAPI

from zygos.api.routes_runtime import router
from zygos.providers.fake import FakeEmbedder
from zygos.runtime.bootstrap import build_runtime


def _mount(runtime, *, embedder=None, embedding_model="", session_count=lambda: 0):
    """Bare app carrying the inspection router — no lifespan, no create_app."""
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    app.state.embedder = embedder
    app.state.embedding_model = embedding_model
    app.state.session_count = session_count
    return app


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    )


@pytest.mark.asyncio
async def test_get_runtime_renders_manifest():
    runtime = build_runtime()
    try:
        app = _mount(runtime)
        async with _client(app) as client:
            resp = await client.get("/runtime")
    finally:
        await runtime.aclose()
    assert resp.status_code == 200
    body = resp.json()
    # bare app does not run the lifespan, so the stage is the build default
    assert body["lifecycle_stage"] == "register_capabilities"
    assert body["primary_route"]["provider"] == "ollama"


@pytest.mark.asyncio
async def test_get_runtime_health_routes_and_default_not_probed():
    runtime = build_runtime()
    try:
        app = _mount(runtime, session_count=lambda: 2)
        async with _client(app) as client:
            resp = await client.get("/runtime/health")
    finally:
        await runtime.aclose()
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_sessions"] == 2
    assert body["embedder"]["state"] == "not_probed"
    providers = [r["provider"] for r in body["routes"]]
    assert "ollama" in providers


@pytest.mark.asyncio
async def test_get_runtime_health_probe_healthy_with_fake_embedder():
    runtime = build_runtime()
    try:
        app = _mount(runtime, embedder=FakeEmbedder(), embedding_model="fake-embed")
        async with _client(app) as client:
            resp = await client.get("/runtime/health", params={"probe": "true"})
    finally:
        await runtime.aclose()
    assert resp.status_code == 200
    assert resp.json()["embedder"]["state"] == "healthy"


@pytest.mark.asyncio
async def test_get_runtime_populates_thinking():
    from dataclasses import replace

    from zygos.providers.fake import FakeProvider
    from zygos.thinking.support import ThinkingSupportChecker

    runtime = build_runtime()
    try:
        route = runtime.model_service.select_model()
        runtime = replace(runtime, thinking_support=ThinkingSupportChecker(
            {route.provider: FakeProvider(think_capable=True)}))
        app = _mount(runtime)
        async with _client(app) as client:
            resp = await client.get("/runtime")
    finally:
        await runtime.aclose()
    assert resp.json()["thinking"] == {"supported": True, "reason": None}


class _UnroutableModel:
    """A model service whose every circuit is open."""

    def select_model(self, *a, **k):
        from zygos.errors import ProviderUnavailable
        raise ProviderUnavailable("No eligible provider routes", provider="router")


@pytest.mark.asyncio
async def test_get_runtime_survives_unroutable_model():
    """I2/M6: warm-up checks the config primary route, never select_model()."""
    from dataclasses import replace

    from zygos.providers.fake import FakeProvider
    from zygos.thinking.support import ThinkingSupportChecker

    runtime = build_runtime()
    primary = runtime.config.providers.primary.provider
    try:
        runtime = replace(runtime, model_service=_UnroutableModel(),
                          thinking_support=ThinkingSupportChecker(
                              {primary: FakeProvider(think_capable=True)}))
        app = _mount(runtime)
        async with _client(app) as client:
            resp = await client.get("/runtime")
    finally:
        await runtime.aclose()
    assert resp.status_code == 200
    assert resp.json()["thinking"] == {"supported": True, "reason": None}
