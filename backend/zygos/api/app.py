"""FastAPI app factory + server-owned lifecycle (RFC-0007 §1, §9).

`build_runtime()` stays synchronous; the server performs async startup here:
advance the lifecycle, drain deferred memory work, and close on shutdown. The
frozen RuntimeAssembly is advanced by replacing app.state.runtime, so the
manifest reflects the current stage with no assembly/manifest shape change.
Stability: Experimental.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from zygos.api.permission import WebSocketPromptResolver
from zygos.api.routes_runtime import router as runtime_router
from zygos.api.routes_sessions import router as sessions_router
from zygos.api.session import SessionRegistry
from zygos.api.trace import install_trace_bridge
from zygos.api.turn import TurnDeps
from zygos.api.voice_gate import VoiceGate
from zygos.api.websocket import router as ws_router
from zygos.providers.embedding import Embedder
from zygos.runtime.bootstrap import (
    ACCEPT_REQUESTS_STAGE,
    LOAD_MEMORY_STAGE,
    LOAD_SKILLS_STAGE,
    RuntimeAssembly,
)


def _advance(app: FastAPI, stage: str) -> None:
    app.state.runtime = dataclasses.replace(app.state.runtime, lifecycle_stage=stage)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    runtime = app.state.runtime
    ctx = runtime.new_context()
    try:
        _advance(app, LOAD_SKILLS_STAGE)   # no-op today; SkillService is M6
        _advance(app, LOAD_MEMORY_STAGE)
        if runtime.memory_service is not None:
            await runtime.memory_service.resume(ctx)
            await runtime.memory_service.embed_backlog(ctx)
        if runtime.tools:
            Path(runtime.config.tools.workspace_root).mkdir(parents=True, exist_ok=True)
        if runtime.voice_service is not None:
            await runtime.voice_service.start(ctx)
        _advance(app, ACCEPT_REQUESTS_STAGE)
        yield
    finally:
        registry = getattr(app.state, "registry", None)
        if registry is not None:
            for session in registry.sessions():
                if (
                    session.active_task is not None
                    and not session.active_task.done()
                    and session.active_cancel is not None
                ):
                    session.active_cancel.trip()
        if runtime.voice_service is not None:
            await runtime.voice_service.aclose()
        await app.state.runtime.aclose()


def create_app(
    runtime: RuntimeAssembly,
    *,
    embedder: Embedder | None = None,
    embedding_model: str = "",
    session_count: Callable[[], int] | None = None,
) -> FastAPI:
    app = FastAPI(title="Zygos", lifespan=_lifespan)
    app.state.runtime = runtime
    app.state.embedder = embedder
    app.state.embedding_model = embedding_model

    registry = SessionRegistry(
        new_context=lambda sid: runtime.new_context(session_id=sid),
        clock=time.time,
        new_id=lambda: uuid.uuid4().hex,
    )
    app.state.registry = registry
    resolver = WebSocketPromptResolver(registry, runtime.config.server.prompt_timeout_s)
    runtime.tool_service.bind_resolver(resolver)
    voice_gate = VoiceGate()
    app.state.turn_deps = TurnDeps(
        model_service=runtime.model_service,
        reasoning_factory=runtime.reasoning_factory,
        reasoning_enabled=runtime.config.reasoning.enabled,
        memory_service=runtime.memory_service,
        new_id=lambda: uuid.uuid4().hex,
        tool_service=runtime.tool_service,
        tools=runtime.tools,
        tool_loop_config=runtime.tool_loop_config,
        voice_service=runtime.voice_service,
        voice_gate=voice_gate,
    )
    install_trace_bridge(runtime.event_bus, registry)
    app.state.session_count = session_count if session_count is not None else registry.count

    app.include_router(runtime_router)
    app.include_router(sessions_router)
    app.include_router(ws_router)
    return app


def run_server(runtime, *, host: str, port: int, run=None) -> None:
    """Build the FastAPI app and hand it to the ASGI server (uvicorn by default).

    Lives in the api adapter layer (not the CLI) so the runtime core / CLI never
    import a web framework. uvicorn is imported lazily; the lifespan owns async
    startup and aclose; run() owns the loop.
    """
    app = create_app(runtime, embedder=None, embedding_model="")
    if run is None:
        import uvicorn
        run = uvicorn.run
    run(app, host=host, port=port)
