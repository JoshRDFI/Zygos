import pytest
from zygos.api.frames import CHAT, CONTROL, Frame, decode, encode


def test_encode_decode_round_trip():
    frame = Frame(channel=CHAT, type="user_message", payload={"text": "hi"})
    restored = decode(encode(frame))
    assert restored == frame


def test_decode_malformed_json_returns_none():
    assert decode("not json {{{") is None


def test_decode_non_object_returns_none():
    assert decode("[1, 2, 3]") is None


def test_decode_missing_keys_returns_none():
    assert decode('{"channel": "chat"}') is None  # no type


def test_frame_defaults_empty_payload():
    frame = Frame(channel=CONTROL, type="ping")
    assert frame.payload == {}


def test_frame_is_frozen():
    frame = Frame(channel=CHAT, type="token", payload={"text": "x"})
    with pytest.raises(Exception):
        frame.type = "other"


def test_audio_tag_out_is_distinct():
    from zygos.api.frames import AUDIO_TAG_IN, AUDIO_TAG_OUT
    assert AUDIO_TAG_OUT == 0x01 and AUDIO_TAG_OUT != AUDIO_TAG_IN
