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
