"""Live runtime-health projection for GET /runtime/health (RFC-0007 §8).

Separate from the pure static Manifest: this may probe (opt-in). The embedder
state is tri-state with a passive default of `not_probed`, which resolves the
RFC-0006 T7 false-`unhealthy` for off-route embedders. Stability: Experimental.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from zygos.providers.embedding import Embedder
from zygos.providers.types import EmbedRequest
from zygos.services.router import RouterSnapshot

EmbedderState = Literal["healthy", "unhealthy", "not_probed"]

_PROBE_SENTINEL = "zygos health probe"


class RouteHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str
    circuit: str


class EmbedderHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: str
    model: str
    state: EmbedderState


class RuntimeHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    routes: tuple[RouteHealth, ...]
    embedder: EmbedderHealth
    active_sessions: int


async def probe_embedder(embedder: Embedder, embedding_model: str) -> EmbedderState:
    """Actively embed a sentinel; healthy iff a non-empty vector returns."""
    try:
        result = await embedder.embed(
            EmbedRequest(model=embedding_model, texts=(_PROBE_SENTINEL,))
        )
    except Exception:  # transport/model failure — the model decides nothing here
        return "unhealthy"
    if result.vectors and result.vectors[0]:
        return "healthy"
    return "unhealthy"


async def build_runtime_health(
    *,
    snapshot: RouterSnapshot,
    backend: str,
    embedder: Embedder | None,
    embedding_model: str,
    probe: bool,
    session_count: int,
) -> RuntimeHealth:
    routes = tuple(
        RouteHealth(provider=r.provider, model=r.model, circuit=r.circuit)
        for r in snapshot.routes
    )
    if embedder is not None and probe:
        state: EmbedderState = await probe_embedder(embedder, embedding_model)
    else:
        state = "not_probed"
    return RuntimeHealth(
        routes=routes,
        embedder=EmbedderHealth(backend=backend, model=embedding_model, state=state),
        active_sessions=session_count,
    )
