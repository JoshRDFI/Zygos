"""Inspection routes: GET /runtime (pure) and GET /runtime/health (live).

GET /runtime renders the pure static Manifest — no network, no mutation
(RFC-0003 §5 purity preserved). GET /runtime/health is the live complement.
Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from zygos.api.health import RuntimeHealth, build_runtime_health
from zygos.runtime.manifest import Manifest, mcp_manifest, primary_route, runtime_manifest
from zygos.thinking.support import check_selected

router = APIRouter()


@router.get("/runtime", response_model=Manifest)
async def get_runtime(request: Request) -> Manifest:
    runtime = request.app.state.runtime
    # Warm the support cache for the config primary route (what the manifest reads).
    await check_selected(runtime.thinking_support, lambda: primary_route(runtime.config))
    # The keychain probe can block for seconds: run it off the event loop.
    secrets_status = await asyncio.to_thread(runtime.secrets.status)
    # The MCP record read can wait on a writer: also off the loop.
    mcp_servers = await asyncio.to_thread(mcp_manifest, runtime.mcp.store)
    return runtime_manifest(runtime, secrets_status=secrets_status, mcp_servers=mcp_servers)


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
