"""Two-stage barge-in state machine: duck-then-stop (RFC-0005 voice quality).

A client voice-activity ONSET ducks the assistant (a reversible attenuation
signalled via tts.duck — the client lowers playback gain; the backend keeps
streaming PCM). Confirmed SPEECH stops the turn via the existing cooperative
CancelToken. A false alarm (SILENCE) or a duck timeout restores full volume and
never cancels the assistant. Signals arrive as control:audio.vad frames; the real
VAD producer (the browser) is deferred — this module is the protocol + machine.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from zygos.api.frames import AUDIO_OUT, Frame


def arm_duck(session, *, gain: float, timeout_s: float) -> None:
    """onset: attenuate the assistant if it is speaking (else a no-op)."""
    if not session.speaking or session.ducked:
        return
    session.ducked = True
    session.enqueue(Frame(channel=AUDIO_OUT, type="tts.duck", payload={"gain": gain}))
    session.duck_timeout = asyncio.create_task(_duck_timeout(session, timeout_s))


def release_duck(session) -> None:
    """silence: the onset was noise / has ended — restore full volume (no-op if not ducked)."""
    if not session.ducked:
        return
    _cancel_duck_timeout(session)
    session.ducked = False
    session.enqueue(Frame(channel=AUDIO_OUT, type="tts.unduck", payload={"gain": 1.0}))


def stop_speech(session) -> None:
    """speech confirmed: hard-stop the current turn by tripping its CancelToken.

    Fire-and-forget — it does NOT await the task (keeps the WS reader responsive)
    and does NOT start a new turn (the committed final transcript still drives that).
    """
    _cancel_duck_timeout(session)
    session.ducked = False
    if (
        session.active_task is not None
        and not session.active_task.done()
        and session.active_cancel is not None
    ):
        session.active_cancel.trip()


def clear_duck_state(session) -> None:
    """Drop any duck window silently (TTS ended / teardown) — emits nothing."""
    _cancel_duck_timeout(session)
    session.ducked = False


def _cancel_duck_timeout(session) -> None:
    task = session.duck_timeout
    session.duck_timeout = None
    if task is not None and not task.done():
        task.cancel()


async def _duck_timeout(session, timeout_s: float) -> None:
    try:
        await asyncio.sleep(timeout_s)
    except asyncio.CancelledError:
        return
    if session.ducked:  # unresolved onset — treat as noise, restore volume
        session.ducked = False
        session.duck_timeout = None
        session.enqueue(Frame(channel=AUDIO_OUT, type="tts.unduck", payload={"gain": 1.0}))
