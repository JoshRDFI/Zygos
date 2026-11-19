"""Streams a synthesized reply to the client over the audio.out channel (RFC-0005).

`speak_reply` is awaited inside run_turn, so it is part of session.active_task and
tied to the turn's CancelToken: a barge-in trips ctx.cancelled and this loop breaks
at the next chunk boundary, emitting tts.end(cancelled). A synthesis failure is
isolated to a tts.end(error) frame — it never propagates out of the turn.

A session plays one `speak_reply` stream at a time (``session.speech_lock``); a
second stream, e.g. a permission announce during the "Let me think" prefix, waits.

Stability: Experimental.
"""

from __future__ import annotations

import logging

from zygos.api.duck import clear_duck_state
from zygos.api.frames import AUDIO_OUT, Frame

logger = logging.getLogger("zygos.api.speech")


async def speak_reply(session, voice_service, ctx, text: str, turn_id: str) -> None:
    # One stream at a time per session: a runtime line (a permission announce, a
    # voice-command confirmation) and the turn's own prefix or reply each wait for the
    # one playing, so their audio never interleaves and `speaking` stays honest.
    async with session.speech_lock:
        await _stream(session, voice_service, ctx, text, turn_id)


async def _stream(session, voice_service, ctx, text: str, turn_id: str) -> None:
    synth = voice_service.synthesize_stream(ctx, text)
    fmt = voice_service.tts_format
    session.enqueue(Frame(channel=AUDIO_OUT, type="tts.begin", payload={
        "sample_rate": fmt.sample_rate,
        "channels": fmt.channels,
        "sample_format": fmt.sample_format,
        "turn_id": turn_id,
    }))
    session.speaking = True
    reason = "complete"
    try:
        async for pcm in synth.chunks():
            if ctx.cancelled:
                break
            session.enqueue_audio(pcm)
    except Exception:  # noqa: BLE001 - a synthesis failure must not kill the turn
        reason = "error"
        logger.warning("synthesis failed", exc_info=True)
    finally:
        session.speaking = False
        clear_duck_state(session)
        if reason != "error" and ctx.cancelled:
            reason = "cancelled"
        try:
            await synth.cancel()
            await synth.aclose()
        except Exception:  # noqa: BLE001 - teardown failure must not skip tts.end
            logger.debug("speak_reply: synth teardown failed", exc_info=True)
        session.enqueue(Frame(channel=AUDIO_OUT, type="tts.end",
                              payload={"turn_id": turn_id, "reason": reason}))


async def say(session, deps, text: str) -> None:
    """Speak a short runtime-authored line (e.g. a voice-command confirmation).

    Runs under a fresh child context tied to ``session.active_cancel`` so a barge-in
    cancels it like a turn. Silent unless the speaker is on and TTS is available
    (the same gate as ``turn._speaks_reply``, inlined: turn.py imports this module).
    """
    voice_service = deps.voice_service
    if not (session.speak and voice_service is not None and voice_service.tts_available):
        return
    turn_id = deps.new_id()
    ctx = session.root.child(turn_id, cancel=session.active_cancel)
    await speak_reply(session, voice_service, ctx, text, turn_id)
