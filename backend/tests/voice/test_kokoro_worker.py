import numpy as np

from zygos.voice.sidecar.kokoro import audio_to_pcm, split_sentences


def test_split_sentences_matches_fake_tts_pattern():
    assert split_sentences("Hello there. How are you?  I'm fine!") == \
        ["Hello there.", "How are you?", "I'm fine!"]
    assert split_sentences("   ") == []
    assert split_sentences("no terminal punctuation") == ["no terminal punctuation"]


def test_audio_to_pcm_roundtrip_and_dtype():
    samples = np.array([0.0, 1.0, -1.0, 0.5], dtype=np.float32)
    pcm = audio_to_pcm(samples)
    assert isinstance(pcm, bytes)
    assert len(pcm) == 2 * len(samples)                 # 16-bit -> 2 bytes/sample
    back = np.frombuffer(pcm, dtype="<i2")
    assert back[0] == 0 and back[1] == 32767 and back[2] == -32767


def test_audio_to_pcm_clips_out_of_range():
    pcm = audio_to_pcm(np.array([2.0, -2.0], dtype=np.float32))
    back = np.frombuffer(pcm, dtype="<i2")
    assert back[0] == 32767 and back[1] == -32767
