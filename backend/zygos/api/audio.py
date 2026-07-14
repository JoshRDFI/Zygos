"""Bridges audio.in PCM to VoiceService and drives a turn on the committed transcript.

PCM chunks and the endpoint signal must be strictly serialized (Transcription.push
is stateful — reordering corrupts the utterance). A per-session inbox queue drained
by a single pusher task gives that ordering guarantee without blocking the WS
receive loop on each awaited push.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging

from zygos.api.frames import CHAT, Frame
from zygos.api.turn import TurnDeps, run_turn
from zygos.runtime.context import CancelToken

logger = logging.getLogger("zygos.api.audio")

_ENDPOINT = object()  # inbox sentinel: signals the pusher to call tr.endpoint()


class AudioTurn:
    def __init__(
        self,
        transcription,
        inbox: asyncio.Queue,
        pusher: asyncio.Task,
        consumer: asyncio.Task,
    ) -> None:
        self.transcription = transcription
        self.inbox = inbox
        self.pusher = pusher
        self.consumer = consumer


async def start_audio_turn(session, deps: TurnDeps) -> None:
    if deps.voice_service is None or session.audio is not None:
        return
    inbox: asyncio.Queue = asyncio.Queue()
    tr = deps.voice_service.begin_transcription(session.root)

    async def pusher() -> None:
        while True:
            item = await inbox.get()
            if item is _ENDPOINT:
                await tr.endpoint()
                return
            await tr.push(item)

    async def consume() -> None:
        try:
            async for ev in tr.events():
                if ev.kind == "partial":
                    session.enqueue(Frame(channel=CHAT, type="partial", payload={"text": ev.text}))
                else:  # final
                    session.enqueue(Frame(channel=CHAT, type="final", payload={"text": ev.text}))
                    if session.active_task is not None and not session.active_task.done():
                        if session.active_cancel is not None:
                            session.active_cancel.trip()
                        await session.active_task  # barge-in: unwind the prior turn first
                    token = CancelToken()
                    session.active_cancel = token
                    session.active_task = asyncio.create_task(
                        run_turn(session, deps, ev.text, token))
        except Exception:  # noqa: BLE001 - a failed transcription must not kill the socket
            session.enqueue(Frame(channel=CHAT, type="error",
                                  payload={"message": "transcription failed"}))
        finally:
            session.audio = None

    session.audio = AudioTurn(tr, inbox, asyncio.create_task(pusher()), asyncio.create_task(consume()))


def feed_audio(session, pcm: bytes) -> None:
    audio = session.audio
    if audio is not None:
        audio.inbox.put_nowait(pcm)


async def end_audio_turn(session) -> None:
    if session.audio is not None:
        session.audio.inbox.put_nowait(_ENDPOINT)


async def cancel_audio_turn(session) -> None:
    audio = session.audio
    if audio is not None:
        try:
            await audio.transcription.cancel()
        except Exception:  # noqa: BLE001 - a dead sidecar must not kill the session
            logger.debug("cancel_audio_turn: transcription.cancel() failed", exc_info=True)
        audio.pusher.cancel()
        audio.consumer.cancel()
        session.audio = None
