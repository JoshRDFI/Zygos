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


from types import SimpleNamespace

from zygos.voice.sidecar import kokoro as worker


class _Ort:
    def __init__(self, landed):
        self.landed = landed
        self.preloaded = 0
        self.asked = None

    def preload_dlls(self):
        self.preloaded += 1

    def get_available_providers(self):
        return ["CPUExecutionProvider"]

    def InferenceSession(self, path, providers):  # noqa: N802
        self.asked = providers
        return SimpleNamespace(get_providers=lambda: self.landed)


class _KokoroCls:
    @classmethod
    def from_session(cls, session, voices_path):
        return ("kokoro", session, voices_path)


def _fake_assets(monkeypatch):
    monkeypatch.setattr(worker, "ensure_assets", lambda root: ("/m.onnx", "/v.bin"))


def test_load_kokoro_cuda_lands_on_cuda(monkeypatch):
    _fake_assets(monkeypatch)
    ort = _Ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
    k, active, reason = worker._load_kokoro("cuda", ort_module=ort, kokoro_cls=_KokoroCls)
    assert active == "cuda" and reason is None
    assert ort.preloaded == 1 and ort.asked[0] == "CUDAExecutionProvider"
    assert k[0] == "kokoro" and k[2] == "/v.bin"


def test_load_kokoro_cuda_silent_cpu_fallback_reports_reason(monkeypatch):
    _fake_assets(monkeypatch)
    _k, active, reason = worker._load_kokoro("cuda", ort_module=_Ort(["CPUExecutionProvider"]),
                                             kokoro_cls=_KokoroCls)
    assert active == "cpu" and "CUDAExecutionProvider unavailable" in reason


def test_load_kokoro_cpu_default(monkeypatch):
    _fake_assets(monkeypatch)
    ort = _Ort(["CPUExecutionProvider"])
    _k, active, reason = worker._load_kokoro(ort_module=ort, kokoro_cls=_KokoroCls)
    assert (active, reason, ort.preloaded, ort.asked) == ("cpu", None, 0, ["CPUExecutionProvider"])


def test_health_reply_shapes():
    assert worker.health_reply("cuda", None) == {"type": "health_ok", "device": "cuda"}
    assert worker.health_reply("cpu", "why") == {"type": "health_ok", "device": "cpu", "reason": "why"}


def test_self_check_exit_codes(monkeypatch):
    lines = []
    synth = lambda k, s, v, l: None  # noqa: E731
    monkeypatch.setenv("ZYGOS_TTS_DEVICE", "cuda")
    ok = worker.self_check(load=lambda device: ("k", "cuda", None), synth=synth, out=lines.append)
    assert ok == 0 and any("device=cuda" in ln for ln in lines)

    lines.clear()
    bad = worker.self_check(load=lambda device: ("k", "cpu", "no cuda"), synth=synth, out=lines.append)
    assert bad == 1 and any("device=cpu" in ln for ln in lines) and any("no cuda" in ln for ln in lines)


def test_self_check_load_error_is_nonzero(monkeypatch):
    monkeypatch.setenv("ZYGOS_TTS_DEVICE", "cuda")
    def boom(device):
        raise RuntimeError("libcudnn missing")
    lines = []
    assert worker.self_check(load=boom, synth=lambda *a: None, out=lines.append) == 1
    assert any("libcudnn missing" in ln for ln in lines)
