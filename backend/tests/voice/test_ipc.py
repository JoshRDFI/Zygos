import json

import pytest

from zygos.voice.errors import IpcProtocolError
from zygos.voice.ipc import KIND_CONTROL, KIND_PCM, encode_frame, FrameDecoder


def _roundtrip(*frames):
    dec = FrameDecoder()
    blob = b"".join(encode_frame(k, b) for k, b in frames)
    dec.feed(blob)
    return list(dec.frames())


def test_control_and_pcm_roundtrip():
    ctrl = json.dumps({"type": "start"}).encode()
    pcm = b"\x01\x02\x03\x04"
    assert _roundtrip((KIND_CONTROL, ctrl), (KIND_PCM, pcm)) == [
        (KIND_CONTROL, ctrl),
        (KIND_PCM, pcm),
    ]


def test_partial_delivery_yields_nothing_until_complete():
    dec = FrameDecoder()
    frame = encode_frame(KIND_PCM, b"abcd")
    dec.feed(frame[:3])
    assert list(dec.frames()) == []
    dec.feed(frame[3:])
    assert list(dec.frames()) == [(KIND_PCM, b"abcd")]


def test_oversized_frame_raises():
    dec = FrameDecoder()
    # length header claiming a huge frame
    dec.feed((99_000_000).to_bytes(4, "big"))
    with pytest.raises(IpcProtocolError):
        list(dec.frames())


# append to backend/tests/voice/test_ipc.py
import asyncio


async def test_transport_control_and_pcm_between_two_endpoints():
    listener = await __import__("zygos.voice.ipc", fromlist=["listen"]).listen()
    from zygos.voice.ipc import connect

    async def server():
        conn = await listener.accept()
        kind, body = await conn.recv()
        assert kind == "control" and body == {"type": "start", "sample_rate": 16000}
        kind, body = await conn.recv()
        assert kind == "pcm" and body == b"\x00\x01"
        await conn.send_control({"type": "final", "text": "ok"})
        await conn.close()

    server_task = asyncio.create_task(server())
    client = await connect(listener.address)
    await client.send_control({"type": "start", "sample_rate": 16000})
    await client.send_pcm(b"\x00\x01")
    kind, body = await client.recv()
    assert kind == "control" and body["text"] == "ok"
    await client.close()
    await server_task
    await listener.close()


# append to test_ipc.py
async def test_recv_surfaces_frames_fed_incrementally_over_socket():
    listener = await __import__("zygos.voice.ipc", fromlist=["listen"]).listen()
    from zygos.voice.ipc import connect
    server_conn: list = []

    async def server():
        server_conn.append(await listener.accept())

    t = asyncio.create_task(server())
    client = await connect(listener.address)
    await t
    for i in range(5):
        await client.send_pcm(bytes([i]))
    got = [await server_conn[0].recv() for _ in range(5)]
    assert [b for _, b in got] == [bytes([i]) for i in range(5)]
    await client.close()
    await server_conn[0].close()
    await listener.close()
