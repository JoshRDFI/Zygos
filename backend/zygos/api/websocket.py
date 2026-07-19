"""Per-session WebSocket handler (RFC-0007 §1, §5, §6).

One writer task drains the session's outbound queue (total ordering, no
concurrent send). The reader loop dispatches frames: a new user_message barges
in on any active turn (trip + await), then starts a fresh turn; control:cancel
trips the active turn; ping/pong and hello are handled inline. Disconnect trips
the active turn and drops the socket. A replacement connection supersedes the
old one without its teardown clobbering the new state.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from zygos.api.audio import cancel_audio_turn, end_audio_turn, feed_audio, start_audio_turn
from zygos.api.duck import arm_duck, release_duck, stop_speech
from zygos.api.frames import AUDIO_TAG_IN, CHAT, CONTROL, TOOLS, Frame, decode, encode
from zygos.api.session import Session
from zygos.api.turn import TurnDeps, run_turn
from zygos.runtime.context import CancelToken

logger = logging.getLogger("zygos.api.websocket")

router = APIRouter()


async def _writer(websocket: WebSocket, session: Session) -> None:
    while True:
        item = await session.outbound.get()
        try:
            if isinstance(item, (bytes, bytearray)):
                await websocket.send_bytes(bytes(item))
            else:
                await websocket.send_text(encode(item))
        except asyncio.CancelledError:
            raise  # teardown's writer.cancel() must still work
        except Exception:  # noqa: BLE001 - client dropped mid-turn; stop draining quietly
            logger.debug("writer: send failed (session=%s), stopping drain", session.id)
            return


def _acquire_voice_or_warn(session: Session, deps: TurnDeps) -> bool:
    """Gate voice to one session at a time for shared local sidecars. Returns
    True (and takes ownership) if the session may use voice; returns False and
    warns the client otherwise. Inert when there is no voice service, no gate,
    or the engine is concurrency-safe (API-backed)."""
    vs = deps.voice_service
    gate = deps.voice_gate
    if vs is None or gate is None or vs.concurrent_sessions_ok:
        return True
    if gate.try_acquire(session.id):
        return True
    session.enqueue(Frame(channel=CONTROL, type="audio.unavailable",
                          payload={"reason": "voice_in_use",
                                   "message": "Voice is active in another session."}))
    return False


async def _dispatch(session: Session, deps: TurnDeps, frame: Frame) -> None:
    if frame.channel == CHAT and frame.type == "user_message":
        text = str(frame.payload.get("text", ""))
        if session.active_task is not None and not session.active_task.done():
            if session.active_cancel is not None:
                session.active_cancel.trip()
            await session.active_task  # barge-in: unwind prior turn
        token = CancelToken()
        session.active_cancel = token
        session.active_task = asyncio.create_task(run_turn(session, deps, text, token))
    elif frame.channel == CONTROL and frame.type == "cancel":
        if session.active_cancel is not None:
            session.active_cancel.trip()
        await cancel_audio_turn(session)
    elif frame.channel == CONTROL and frame.type == "ping":
        session.enqueue(Frame(channel=CONTROL, type="pong", payload={}))
    elif frame.channel == CONTROL and frame.type == "hello":
        session.enqueue(Frame(channel=CONTROL, type="hello", payload={"ready": True}))
    elif frame.channel == TOOLS and frame.type == "permission_response":
        call_id = str(frame.payload.get("call_id", ""))
        decision = frame.payload.get("decision")
        fut = session.pending_permissions.get(call_id)
        if fut is not None and not fut.done() and decision in ("allow", "deny"):
            fut.set_result(decision)
    elif frame.channel == CONTROL and frame.type == "audio.start":
        if _acquire_voice_or_warn(session, deps):
            await start_audio_turn(session, deps)
    elif frame.channel == CONTROL and frame.type == "audio.endpoint":
        await end_audio_turn(session)
    elif frame.channel == CONTROL and frame.type == "audio.output":
        if not bool(frame.payload.get("enabled", False)):
            session.speak = False  # disabling never gated; does not release ownership
        elif _acquire_voice_or_warn(session, deps):
            session.speak = True
    elif frame.channel == CONTROL and frame.type == "audio.vad":
        state = frame.payload.get("state")
        if state == "onset":
            arm_duck(session, gain=deps.duck_gain, timeout_s=deps.duck_timeout_s)
        elif state == "speech":
            stop_speech(session)
        elif state == "silence":
            release_duck(session)
        # unknown state ignored
    # unknown (channel, type) ignored — forward-compat rule


@router.websocket("/ws/session/{session_id}")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    registry = websocket.app.state.registry
    deps = websocket.app.state.turn_deps
    await websocket.accept()
    session = registry.get(session_id)
    if session is None:
        await websocket.close(code=4404)
        return

    # Replace any prior connection to this session (reconnect, not multiplex).
    if session._writer is not None:
        session._writer.cancel()
    conn = object()
    session._conn = conn
    session.connected = True
    writer = asyncio.create_task(_writer(websocket, session))
    session._writer = writer

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data is not None:
                if data and data[0] == AUDIO_TAG_IN:
                    feed_audio(session, data[1:])
                continue
            raw = message.get("text")
            if raw is None:
                continue
            frame = decode(raw)
            if frame is None:
                session.enqueue(Frame(channel=CONTROL, type="error",
                                      payload={"message": "malformed frame"}))
                continue
            await _dispatch(session, deps, frame)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - never let a handler crash escape
        logger.exception("websocket handler error (session=%s)", session_id)
    finally:
        if session._conn is conn:  # only if not superseded by a replacement
            if session.audio is not None:
                session.audio.consumer.cancel()
                session.audio.pusher.cancel()
                session.audio = None
            session.speaking = False
            session.connected = False
            gate = getattr(deps, "voice_gate", None)
            if gate is not None:
                gate.release(session.id)
            for fut in list(session.pending_permissions.values()):
                if not fut.done():
                    fut.set_result("deny")
            session.pending_permissions.clear()
            session._writer = None
            # Reap the abandoned session: with the app-lifetime singleton client,
            # WS-close == page-gone. delete() also trips any active turn and clears
            # the duck window, so this is the sole owner of that teardown. Guarded
            # by `session._conn is conn`, so a superseding reconnect (which reassigns
            # session._conn) never reaps the live session. Assumption holds until a
            # reconnect feature adds a grace period.
            registry.delete(session.id)
        writer.cancel()
