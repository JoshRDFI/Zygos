import dataclasses

import httpx
import pytest

from zygos.api.app import create_app
from zygos.runtime.bootstrap import build_runtime


class _SpyMemory:
    def __init__(self):
        self.resume_calls = 0
        self.embed_calls = 0

    async def resume(self, ctx):
        self.resume_calls += 1
        return 0

    async def embed_backlog(self, ctx):
        self.embed_calls += 1
        return 0


@pytest.mark.asyncio
async def test_startup_drains_memory_and_reaches_accept_requests():
    spy = _SpyMemory()
    runtime = dataclasses.replace(build_runtime(), memory_service=spy)
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        assert app.state.runtime.lifecycle_stage == "accept_requests"
        assert spy.resume_calls == 1
        assert spy.embed_calls == 1
    # shutdown closed the shared http client
    assert app.state.runtime.http_client.is_closed


@pytest.mark.asyncio
async def test_startup_skips_drain_when_memory_disabled():
    runtime = dataclasses.replace(build_runtime(), memory_service=None)
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        assert app.state.runtime.lifecycle_stage == "accept_requests"
    assert app.state.runtime.http_client.is_closed


@pytest.mark.asyncio
async def test_create_app_stores_injected_state():
    runtime = build_runtime()
    try:
        app = create_app(runtime, embedding_model="m", session_count=lambda: 7)
        assert app.state.embedder is None
        assert app.state.embedding_model == "m"
        assert app.state.session_count() == 7
    finally:
        await runtime.aclose()


@pytest.mark.asyncio
async def test_get_runtime_shows_accept_requests_after_startup():
    """Integration: create_app wires routes AND lifespan together."""
    # memory_service=None keeps the lifespan hermetic (no real store/DB touch)
    runtime = dataclasses.replace(build_runtime(), memory_service=None)
    app = create_app(runtime)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://t"
        ) as client:
            resp = await client.get("/runtime")
    assert resp.json()["lifecycle_stage"] == "accept_requests"
