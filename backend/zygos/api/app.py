"""FastAPI app factory + server-owned lifecycle (RFC-0007 §1, §9).

`build_runtime()` stays synchronous; the server performs async startup here:
advance the lifecycle, drain deferred memory work, and close on shutdown. The
frozen RuntimeAssembly is advanced by replacing app.state.runtime, so the
manifest reflects the current stage with no assembly/manifest shape change.
Stability: Experimental.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from zygos.api.routes_runtime import router as runtime_router
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
        _advance(app, ACCEPT_REQUESTS_STAGE)
        yield
    finally:
        # Cycle 2 will trip active turns' CancelTokens here before closing.
        await app.state.runtime.aclose()


def create_app(
    runtime: RuntimeAssembly,
    *,
    embedder: Embedder | None = None,
    embedding_model: str = "",
    session_count: Callable[[], int] = lambda: 0,
) -> FastAPI:
    app = FastAPI(title="Zygos", lifespan=_lifespan)
    app.state.runtime = runtime
    app.state.embedder = embedder
    app.state.embedding_model = embedding_model
    app.state.session_count = session_count
    app.include_router(runtime_router)
    return app


def run_server(runtime, *, host: str, port: int, run=None) -> None:
    """Build the FastAPI app and hand it to the ASGI server (uvicorn by default).

    Lives in the api adapter layer (not the CLI) so the runtime core / CLI never
    import a web framework. uvicorn is imported lazily; the lifespan owns async
    startup and aclose; run() owns the loop.
    """
    app = create_app(runtime, embedder=None, embedding_model="", session_count=lambda: 0)
    if run is None:
        import uvicorn
        run = uvicorn.run
    run(app, host=host, port=port)
