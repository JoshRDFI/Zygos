"""Model picker routes: GET /models, PUT/DELETE /models/default, GET /hardware
(RFC-0013 §1-§4, §10, §11).

Both are live: they rescan the hardware (in a thread) and, for /models, read
Ollama. GET /runtime stays pure and only carries the last scan.
Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from zygos.hardware.probe import HardwareSnapshot
from zygos.models.catalog import ModelEntry, ModelsView
from zygos.models.choices import DefaultModel, ModelChoices
from zygos.providers.types import LLAMACPP_PROVIDER, ollama_name
from zygos.services.router import RouteChoice

router = APIRouter()


@router.get("/models", response_model=ModelsView)
async def get_models(request: Request) -> ModelsView:
    runtime = request.app.state.runtime
    return await runtime.model_catalog.view(runtime.new_context())


@router.get("/hardware", response_model=HardwareSnapshot)
async def get_hardware(request: Request) -> HardwareSnapshot:
    return await asyncio.to_thread(request.app.state.runtime.hardware.scan)


LLAMACPP_REFUSAL = "llama.cpp models can't answer yet — Zygos starts llama-server in a later phase"


class SetDefault(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    confirm: bool = False


def _find(view: ModelsView, provider: str, model: str) -> ModelEntry | None:
    def norm(p: str, m: str) -> str:
        return ollama_name(m) if p == "ollama" else m

    want = norm(provider, model)
    return next((e for e in view.models if e.provider == provider and norm(e.provider, e.name) == want), None)


@router.put("/models/default", response_model=ModelsView)
async def put_default(body: SetDefault, request: Request):
    runtime = request.app.state.runtime
    view = await runtime.model_catalog.view(runtime.new_context())
    entry = _find(view, body.provider, body.model)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"{body.provider}/{body.model} isn't listed")
    if entry.provider == LLAMACPP_PROVIDER:
        raise HTTPException(status_code=409, detail=LLAMACPP_REFUSAL)
    if entry.location == "local" and entry.fit is not None and entry.fit.level in ("no", "unknown") \
            and not body.confirm:
        return JSONResponse(status_code=409, content={
            "detail": entry.fit_text or f"fit: {entry.fit.level}",
            "fit": entry.fit.level, "needs_confirm": True})
    choices = runtime.model_choices.get().model_copy(
        update={"default_model": DefaultModel(provider=entry.provider, model=entry.name)})
    await asyncio.to_thread(runtime.model_choices.set, ModelChoices.model_validate(choices.model_dump()))
    # Only Ollama has residency to manage; vLLM and cloud models need no load.
    if entry.provider == "ollama" and runtime.residency is not None:
        runtime.residency.preload(RouteChoice(entry.provider, entry.name))
    return await runtime.model_catalog.view(runtime.new_context())


@router.delete("/models/default", response_model=ModelsView)
async def delete_default(request: Request) -> ModelsView:
    runtime = request.app.state.runtime
    choices = runtime.model_choices.get().model_copy(update={"default_model": None})
    await asyncio.to_thread(runtime.model_choices.set, ModelChoices.model_validate(choices.model_dump()))
    return await runtime.model_catalog.view(runtime.new_context())
