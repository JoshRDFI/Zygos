"""REST session resource surface (RFC-0007 §4).

Server-authoritative ids; snapshots only. The SessionRegistry lives on
app.state.registry (wired in app.py).

Stability: Experimental.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.post("/sessions")
async def create_session(request: Request) -> dict:
    session = request.app.state.registry.create()
    return {"id": session.id}


@router.get("/sessions")
async def list_sessions(request: Request) -> list[dict]:
    return [s.model_dump() for s in request.app.state.registry.list()]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request) -> dict:
    session = request.app.state.registry.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session.snapshot().model_dump()


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request) -> dict:
    if not request.app.state.registry.delete(session_id):
        raise HTTPException(status_code=404, detail="session not found")
    return {"deleted": session_id}
