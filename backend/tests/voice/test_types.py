from zygos.voice.types import (
    AudioFormat, TranscriptEvent, SttEngineSpec,
    StartMsg, FinalMsg, SAMPLE_RATE_HZ, SAMPLE_FORMAT,
)


def test_audio_format_defaults_are_canonical():
    fmt = AudioFormat()
    assert (fmt.sample_rate, fmt.channels, fmt.sample_format) == (16000, 1, "s16le")


def test_transcript_event_kinds():
    assert TranscriptEvent(kind="partial", text="he").kind == "partial"
    assert TranscriptEvent(kind="final", text="hello").text == "hello"


def test_control_messages_carry_type_tag():
    assert StartMsg().type == "start"
    assert FinalMsg(text="hi").model_dump() == {"type": "final", "text": "hi"}


def test_engine_spec_is_frozen():
    spec = SttEngineSpec(name="fake", argv=("python", "-m", "x"))
    assert spec.device == "cpu"
    import pytest
    with pytest.raises(Exception):
        spec.name = "other"  # frozen
