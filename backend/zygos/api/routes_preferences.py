"""Preferences routes: GET/PUT /preferences (RFC-0010 §4).

Thin REST surface over the runtime's PreferencesStore. PUT takes a full
Personalization body (validated by pydantic -> 422 on bad input, nothing
written); the turn loop reads the same store each turn, so changes apply live.
Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from zygos.personalization import Personalization

router = APIRouter()


@router.get("/preferences", response_model=Personalization)
async def get_preferences(request: Request) -> Personalization:
    return request.app.state.runtime.preferences.get()


@router.put("/preferences", response_model=Personalization)
async def put_preferences(body: Personalization, request: Request) -> Personalization:
    store = request.app.state.runtime.preferences
    store.set(body)
    return store.get()
