import pytest

from zygos.api.health import (
    EmbedderHealth,
    RouteHealth,
    RuntimeHealth,
    build_runtime_health,
    probe_embedder,
)
from zygos.providers.fake import FakeEmbedder
from zygos.providers.types import EmbedRequest, EmbedResult, Usage
from zygos.services.router import RouteStatus, RouterSnapshot


def _snapshot():
    return RouterSnapshot(
        routes=(
            RouteStatus(
                provider="ollama",
                model="qwen3",
                circuit="closed",
                consecutive_failures=0,
                requests_in_window=0,
                last_error_code=None,
            ),
        )
    )


class _RaisingEmbedder:
    name = "boom"

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        raise RuntimeError("no model")


@pytest.mark.asyncio
async def test_probe_healthy_with_fake_embedder():
    assert await probe_embedder(FakeEmbedder(), "fake-embed") == "healthy"


@pytest.mark.asyncio
async def test_probe_unhealthy_when_embedder_raises():
    assert await probe_embedder(_RaisingEmbedder(), "boom") == "unhealthy"


@pytest.mark.asyncio
async def test_health_not_probed_when_no_embedder():
    health = await build_runtime_health(
        snapshot=_snapshot(), backend="local", embedder=None,
        embedding_model="", probe=True, session_count=0,
    )
    assert health.embedder.state == "not_probed"
    assert health.embedder.backend == "local"


@pytest.mark.asyncio
async def test_health_not_probed_when_probe_false():
    health = await build_runtime_health(
        snapshot=_snapshot(), backend="local", embedder=FakeEmbedder(),
        embedding_model="fake-embed", probe=False, session_count=0,
    )
    assert health.embedder.state == "not_probed"


@pytest.mark.asyncio
async def test_health_healthy_when_probe_true():
    health = await build_runtime_health(
        snapshot=_snapshot(), backend="local", embedder=FakeEmbedder(),
        embedding_model="fake-embed", probe=True, session_count=3,
    )
    assert health.embedder.state == "healthy"
    assert health.embedder.model == "fake-embed"
    assert health.active_sessions == 3


@pytest.mark.asyncio
async def test_health_maps_routes_from_snapshot():
    health = await build_runtime_health(
        snapshot=_snapshot(), backend="local", embedder=None,
        embedding_model="", probe=False, session_count=0,
    )
    assert health.routes == (
        RouteHealth(provider="ollama", model="qwen3", circuit="closed"),
    )
    assert isinstance(health, RuntimeHealth)
