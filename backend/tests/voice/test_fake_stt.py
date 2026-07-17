import asyncio
import sys

import pytest

from zygos.voice.ipc import listen, connect  # noqa: F401  (connect used indirectly)


async def _spawn_worker(address: str, env_extra=None):
    import os
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return await asyncio.create_subprocess_exec(
        sys.executable, "-m", "zygos.voice.sidecar.fake_stt", address,
        stdin=asyncio.subprocess.DEVNULL, env=env, start_new_session=True,
    )


async def test_fake_worker_transcribes_an_utterance():
    listener = await listen()
    proc = await _spawn_worker(listener.address, {"ZYGOS_FAKE_STT_TRANSCRIPT": "hi there"})
    conn = await listener.accept()
    await conn.send_control({"type": "start", "sample_rate": 16000})
    for _ in range(3):
        await conn.send_pcm(b"\x00" * 640)
    await conn.send_control({"type": "end"})

    kinds = []
    final_text = None
    while True:
        _, body = await conn.recv()
        kinds.append(body["type"])
        if body["type"] == "final":
            final_text = body["text"]
            break
    assert "partial" in kinds
    assert final_text == "hi there"

    await conn.close()
    await listener.close()
    proc.terminate()
    await proc.wait()


async def _spawn_fake_stt(env=None):
    import os
    listener = await listen()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "zygos.voice.sidecar.fake_stt", listener.address,
        env={**os.environ, **(env or {})},
    )
    conn = await listener.accept()
    return listener, proc, conn


async def test_fake_stt_cancel_during_utterance_emits_cancelled():
    listener, proc, conn = await _spawn_fake_stt()
    try:
        # start (no pcm, so the worker emits no `partial` to race the terminal)
        await conn.send_control({"type": "start", "sample_rate": 16000})
        await conn.send_control({"type": "cancel"})
        kind, body = await asyncio.wait_for(conn.recv(), 5.0)
        assert kind == "control" and body == {"type": "cancelled"}
    finally:
        await conn.close()
        proc.terminate()
        await proc.wait()
        await listener.close()


async def test_fake_stt_cancel_with_no_active_utterance_is_silent():
    listener, proc, conn = await _spawn_fake_stt()
    try:
        await conn.send_control({"type": "cancel"})  # nothing active
        await conn.send_control({"type": "health"})
        kind, body = await asyncio.wait_for(conn.recv(), 5.0)
        # Only the health_ok comes back; no stray `cancelled`.
        assert kind == "control" and body == {"type": "health_ok"}
    finally:
        await conn.close()
        proc.terminate()
        await proc.wait()
        await listener.close()
