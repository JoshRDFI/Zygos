"""Streams a synthesized reply to the client over the audio.out channel (RFC-0005).

`speak_reply` is awaited inside run_turn, so it is part of session.active_task and
tied to the turn's CancelToken: a barge-in trips ctx.cancelled and this loop breaks
at the next chunk boundary, emitting tts.end(cancelled). A synthesis failure is
isolated to a tts.end(error) frame — it never propagates out of the turn.

Stability: Experimental.
"""

from __future__ import annotations

import logging

from zygos.api.frames import AUDIO_OUT, Frame

logger = logging.getLogger("zygos.api.speech")


async def speak_reply(session, voice_service, ctx, text: str, turn_id: str) -> None:
    synth = voice_service.synthesize_stream(ctx, text)
    fmt = voice_service.tts_format
    session.enqueue(Frame(channel=AUDIO_OUT, type="tts.begin", payload={
        "sample_rate": fmt.sample_rate,
        "channels": fmt.channels,
        "sample_format": fmt.sample_format,
        "turn_id": turn_id,
    }))
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
        if reason != "error" and ctx.cancelled:
            reason = "cancelled"
        await synth.cancel()
        await synth.aclose()
        session.enqueue(Frame(channel=AUDIO_OUT, type="tts.end",
                              payload={"turn_id": turn_id, "reason": reason}))
