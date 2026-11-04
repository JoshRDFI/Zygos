"""Model picker routes: GET /models and GET /hardware (RFC-0013 §1-§3, §11).

Both are live: they rescan the hardware (in a thread) and, for /models, read
Ollama. GET /runtime stays pure and only carries the last scan.
Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request

from zygos.hardware.probe import HardwareSnapshot
from zygos.models.catalog import ModelsView

router = APIRouter()


@router.get("/models", response_model=ModelsView)
async def get_models(request: Request) -> ModelsView:
    runtime = request.app.state.runtime
    return await runtime.model_catalog.view(runtime.new_context())


@router.get("/hardware", response_model=HardwareSnapshot)
async def get_hardware(request: Request) -> HardwareSnapshot:
    return await asyncio.to_thread(request.app.state.runtime.hardware.scan)
