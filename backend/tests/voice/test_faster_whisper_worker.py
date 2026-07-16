import pytest

np = pytest.importorskip("numpy")

from zygos.voice.sidecar import faster_whisper as fw


def test_pcm_to_audio_normalizes_int16_to_float32():
    # int16 max (32767) and min (-32768) -> ~+1.0 / -1.0 float32
    raw = np.array([32767, -32768, 0], dtype=np.int16).tobytes()
    out = fw.pcm_to_audio(raw)
    assert out.dtype == np.float32
    assert out.shape == (3,)
    assert out[0] == pytest.approx(1.0, abs=1e-3)
    assert out[1] == pytest.approx(-1.0, abs=1e-3)
    assert out[2] == 0.0


def test_pcm_to_audio_empty():
    out = fw.pcm_to_audio(b"")
    assert out.shape == (0,)


class _Seg:
    def __init__(self, text): self.text = text


def test_join_segments_concatenates_and_trims():
    assert fw.join_segments([_Seg("  Hello "), _Seg(" world ")]) == "Hello world"


def test_join_segments_empty():
    assert fw.join_segments([]) == ""
