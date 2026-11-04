"""Backends routes: GET/PUT /backends (RFC-0014 sections 2, 10).

Addresses saved here apply after a Zygos restart (reported as restart_required).
Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from zygos.backends.launch import LaunchError, parse_launch
from zygos.backends.settings import BackendsSettings, address_problem, with_resolved_paths
from zygos.backends.view import BackendsView, build_view

router = APIRouter()


async def _view(request: Request, settings: BackendsSettings) -> BackendsView:
    runtime = request.app.state.runtime
    return await build_view(
        settings, runtime.http_client, config=runtime.config,
        address_sources=runtime.address_sources, addresses_at_start=runtime.addresses_at_start,
    )


@router.get("/backends", response_model=BackendsView)
async def get_backends(request: Request) -> BackendsView:
    return await _view(request, request.app.state.runtime.backends.get())


@router.put("/backends", response_model=BackendsView)
async def put_backends(request: Request, body: BackendsSettings):
    problem = address_problem(body)
    if problem is not None:
        field, detail = problem
        return JSONResponse(status_code=422, content={"detail": detail, "field": field})
    texts = [("llamacpp.default_args", body.llamacpp.default_args)]
    texts += [(f"llamacpp.model_args.{n}", t) for n, t in body.llamacpp.model_args.items()]
    for field, text in texts:
        try:
            parse_launch(text)
        except LaunchError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc), "field": field})
    body = with_resolved_paths(body)
    request.app.state.runtime.backends.set(body)
    return await _view(request, body)
