"""Unit tests for zygos.api.audio (Voice Cycle 1, Task 12 review fix + I2 fix).

Finding 3: cancel_audio_turn's IPC call to the sidecar (transcription.cancel(),
which does writer.drain() under the hood) must not be able to kill the whole
session if the sidecar has already died. A dead sidecar raising
ConnectionResetError/BrokenPipeError/OSError there must be swallowed, and the
pusher/consumer tasks must still be cancelled and session.audio still cleared.

I2 (whole-branch review): if transcription fails BEFORE the client sends
audio.endpoint (e.g. the sidecar crashes mid-utterance, AC5), consume()'s
except-branch fires and clears session.audio — but the pusher task is still
parked on `await inbox.get()` waiting for a sentinel that will never arrive.
Neither cancel_audio_turn nor the WS disconnect teardown can reach it anymore
because both guard on `session.audio is not None`. consume()'s finally must
cancel the pusher task directly so it isn't leaked on this path.

Stability: Experimental (test-only).
"""

from __future__ import annotations

import asyncio

from zygos.api.audio import AudioTurn, cancel_audio_turn, start_audio_turn
from zygos.api.frames import CHAT, Frame
from zygos.voice.errors import TranscriptionFailed


class _DeadSidecarTranscription:
    """A transcription whose cancel() does IPC I/O that fails because the
    sidecar process has already died."""

    async def cancel(self) -> None:
        raise ConnectionResetError("sidecar pipe closed")


class _FakeSession:
    def __init__(self, audio: AudioTurn) -> None:
        self.audio: AudioTurn | None = audio


async def _sleep_forever() -> None:
    await asyncio.sleep(3600)


async def test_cancel_audio_turn_swallows_dead_sidecar_ipc_failure():
    pusher = asyncio.create_task(_sleep_forever())
    consumer = asyncio.create_task(_sleep_forever())
    audio = AudioTurn(_DeadSidecarTranscription(), asyncio.Queue(), pusher, consumer)
    session = _FakeSession(audio)

    await cancel_audio_turn(session)  # must not raise despite the IPC failure

    assert session.audio is None
    # give the event loop a tick to apply the requested cancellation
    await asyncio.sleep(0)
    assert pusher.cancelled() or pusher.done()
    assert consumer.cancelled() or consumer.done()


class _FailingTranscription:
    """A transcription whose events() raises promptly (sidecar crash mid-utterance,
    AC5) without ever yielding a final event. push()/endpoint() await normally but
    are never called here, because the client never sends audio.endpoint on this
    path — that is exactly what leaves the pusher parked on `inbox.get()`."""

    async def push(self, pcm: bytes) -> None:
        pass

    async def endpoint(self) -> None:
        pass

    async def events(self):
        raise TranscriptionFailed("sidecar crashed mid-utterance")
        yield  # pragma: no cover - unreachable; makes this an async generator

    async def cancel(self) -> None:
        pass


class _FakeVoiceService:
    def __init__(self, transcription) -> None:
        self._transcription = transcription

    def begin_transcription(self, ctx):
        return self._transcription


class _FakeDeps:
    def __init__(self, voice_service) -> None:
        self.voice_service = voice_service


class _FakeSessionForStart:
    def __init__(self) -> None:
        self.root = None
        self.audio: AudioTurn | None = None
        self.frames: list[Frame] = []
        self.active_task = None
        self.active_cancel = None

    def enqueue(self, frame: Frame) -> None:
        self.frames.append(frame)


async def test_start_audio_turn_cancels_pusher_when_transcription_fails_before_endpoint():
    session = _FakeSessionForStart()
    deps = _FakeDeps(_FakeVoiceService(_FailingTranscription()))

    await start_audio_turn(session, deps)
    audio = session.audio
    assert audio is not None
    pusher_task, consumer_task = audio.pusher, audio.consumer

    # No audio.endpoint sentinel is ever sent on this path — the pusher would
    # be permanently parked on inbox.get() if nothing cancels it.
    await consumer_task
    await asyncio.sleep(0)  # let the requested cancellation apply

    assert pusher_task.cancelled() or pusher_task.done()
    assert session.audio is None
    assert any(f.channel == CHAT and f.type == "error" for f in session.frames)
