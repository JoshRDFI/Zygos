"""Inspection routes: GET /runtime (pure) and GET /runtime/health (live).

GET /runtime renders the pure static Manifest — no network, no mutation
(RFC-0003 §5 purity preserved). GET /runtime/health is the live complement.
Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from zygos.api.health import RuntimeHealth, build_runtime_health
from zygos.runtime.manifest import Manifest, runtime_manifest

router = APIRouter()


@router.get("/runtime", response_model=Manifest)
async def get_runtime(request: Request) -> Manifest:
    return runtime_manifest(request.app.state.runtime)


@router.get("/runtime/health", response_model=RuntimeHealth)
async def get_runtime_health(request: Request, probe: bool = False) -> RuntimeHealth:
    runtime = request.app.state.runtime
    return await build_runtime_health(
        snapshot=runtime.router_snapshot(),
        backend=runtime.config.memory.embedding.backend,
        embedder=request.app.state.embedder,
        embedding_model=request.app.state.embedding_model,
        probe=probe,
        session_count=request.app.state.session_count(),
    )
