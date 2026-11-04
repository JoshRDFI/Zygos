"""Inspection routes: GET /runtime (pure) and GET /runtime/health (live).

GET /runtime renders the pure static Manifest — no network, no mutation
(RFC-0003 §5 purity preserved). GET /runtime/health is the live complement.
Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from zygos.api.health import RuntimeHealth, build_runtime_health
from zygos.runtime.manifest import Manifest, primary_route, runtime_manifest
from zygos.thinking.support import check_selected

router = APIRouter()


@router.get("/runtime", response_model=Manifest)
async def get_runtime(request: Request) -> Manifest:
    runtime = request.app.state.runtime
    # Warm the support cache for the config primary route (what the manifest reads).
    await check_selected(runtime.thinking_support, lambda: primary_route(runtime.config))
    return runtime_manifest(runtime)


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
