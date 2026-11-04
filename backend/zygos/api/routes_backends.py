"""Backends routes: GET/PUT /backends (RFC-0014 sections 2, 10).

Addresses saved here apply after a Zygos restart (reported as restart_required).
Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from zygos.backends.launch import LaunchError, parse_launch
from zygos.backends.settings import BackendsSettings
from zygos.backends.view import BackendsView, build_view

router = APIRouter()


async def _view(request: Request, settings: BackendsSettings) -> BackendsView:
    runtime = request.app.state.runtime
    return await build_view(
        settings, runtime.http_client, runtime.address_sources, runtime.addresses_at_start
    )


@router.get("/backends", response_model=BackendsView)
async def get_backends(request: Request) -> BackendsView:
    return await _view(request, request.app.state.runtime.backends.get())


@router.put("/backends", response_model=BackendsView)
async def put_backends(request: Request, body: BackendsSettings):
    texts = [("llamacpp.default_args", body.llamacpp.default_args)]
    texts += [(f"llamacpp.model_args.{n}", t) for n, t in body.llamacpp.model_args.items()]
    for field, text in texts:
        try:
            parse_launch(text)
        except LaunchError as exc:
            return JSONResponse(status_code=422, content={"detail": str(exc), "field": field})
    request.app.state.runtime.backends.set(body)
    return await _view(request, body)
