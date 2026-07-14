"""Unit tests for zygos.api.audio (Voice Cycle 1, Task 12 review fix).

Finding 3: cancel_audio_turn's IPC call to the sidecar (transcription.cancel(),
which does writer.drain() under the hood) must not be able to kill the whole
session if the sidecar has already died. A dead sidecar raising
ConnectionResetError/BrokenPipeError/OSError there must be swallowed, and the
pusher/consumer tasks must still be cancelled and session.audio still cleared.

Stability: Experimental (test-only).
"""

from __future__ import annotations

import asyncio

from zygos.api.audio import AudioTurn, cancel_audio_turn


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
