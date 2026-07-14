"""Drives the real fake_tts child process over the real IPC transport."""
from __future__ import annotations

import asyncio
import sys

from zygos.voice.ipc import listen

_SAMPLES_PER_CHAR = 80


async def _spawn(listener):
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "zygos.voice.sidecar.fake_tts", listener.address,
        stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
    )


async def test_synthesize_streams_one_chunk_per_sentence_then_end():
    listener = await listen()
    proc = await _spawn(listener)
    conn = None
    try:
        conn = await asyncio.wait_for(listener.accept(), 5.0)
        await conn.send_control({"type": "synthesize", "text": "One. Two.", "sample_rate": 24000})
        chunks: list[bytes] = []
        while True:
            kind, body = await asyncio.wait_for(conn.recv(), 5.0)
            if kind == "pcm":
                chunks.append(body)
            elif body.get("type") == "end":
                break
        assert len(chunks) == 2
        assert len(chunks[0]) == 2 * _SAMPLES_PER_CHAR * len("One.")
        assert len(chunks[1]) == 2 * _SAMPLES_PER_CHAR * len("Two.")
        assert set(chunks[0]) == {0}  # 16-bit silence
    finally:
        proc.kill()
        await proc.wait()
        # Python 3.12.1+ Server.wait_closed() blocks until all accepted
        # connections are also closed, so the server-side conn must be
        # closed before the listener (mirrors test_fake_stt.py).
        if conn is not None:
            await conn.close()
        await listener.close()


async def test_health_roundtrip():
    listener = await listen()
    proc = await _spawn(listener)
    conn = None
    try:
        conn = await asyncio.wait_for(listener.accept(), 5.0)
        await conn.send_control({"type": "health"})
        kind, body = await asyncio.wait_for(conn.recv(), 5.0)
        assert kind == "control" and body["type"] == "health_ok"
    finally:
        proc.kill()
        await proc.wait()
        if conn is not None:
            await conn.close()
        await listener.close()
