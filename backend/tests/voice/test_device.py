from types import SimpleNamespace

from zygos.voice.device import (
    DEFAULT_GPU_VENV, SETUP_HINT, OnnxSession, WorkerLaunch, active_device,
    onnx_providers, open_onnx_session, preload_gpu_libs, resolve_worker_launch,
    venv_python,
)

MAIN = "/main/python"
VENV_PY = "/v/bin/python"


def _exists(*present):
    return lambda p: p in present


def test_venv_python_posix_and_windows():
    assert venv_python("/v", os_name="posix") == "/v/bin/python"
    assert venv_python("C:/v", os_name="nt").replace("\\", "/") == "C:/v/Scripts/python.exe"


def test_default_gpu_venv_path():
    assert DEFAULT_GPU_VENV == ".zygos/venvs/voice-gpu"


def test_cpu_always_uses_main_interpreter():
    got = resolve_worker_launch("cpu", None, VENV_PY, exists=_exists(VENV_PY), main_python=MAIN)
    assert got == WorkerLaunch(python=MAIN, device="cpu", fallback_reason=None)


def test_cuda_with_managed_venv_present():
    got = resolve_worker_launch("cuda", None, VENV_PY, exists=_exists(VENV_PY), main_python=MAIN)
    assert got == WorkerLaunch(python=VENV_PY, device="cuda", fallback_reason=None)


def test_cuda_with_managed_venv_missing_falls_back_with_hint():
    got = resolve_worker_launch("cuda", None, VENV_PY, exists=_exists(), main_python=MAIN)
    assert got.python == MAIN and got.device == "cpu"
    assert VENV_PY in got.fallback_reason and SETUP_HINT in got.fallback_reason


def test_worker_python_override_present_wins_over_managed():
    got = resolve_worker_launch("cuda", "/custom/py", VENV_PY,
                                exists=_exists("/custom/py", VENV_PY), main_python=MAIN)
    assert got == WorkerLaunch(python="/custom/py", device="cuda", fallback_reason=None)


def test_worker_python_override_missing_names_that_path_not_managed():
    # Review Focus #2: a bad override must not silently use the managed venv.
    got = resolve_worker_launch("cuda", "/custom/py", VENV_PY,
                                exists=_exists(VENV_PY), main_python=MAIN)
    assert got.python == MAIN and got.device == "cpu"
    assert "/custom/py" in got.fallback_reason
    assert SETUP_HINT not in got.fallback_reason   # user-supplied path: setup-gpu won't fix it


def test_managed_venv_missing_reason_uses_absolute_path(tmp_path, monkeypatch):
    # DEFAULT_GPU_VENV is intentionally cwd-relative; the printed reason must
    # still be diagnosable when the doctor/CLI runs from an unexpected cwd.
    monkeypatch.chdir(tmp_path)
    got = resolve_worker_launch("cuda", None, "relvenv/bin/python", exists=_exists(), main_python=MAIN)
    assert str(tmp_path / "relvenv" / "bin" / "python") in got.fallback_reason


def test_worker_python_override_missing_reason_uses_absolute_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    got = resolve_worker_launch("cuda", "relworker/python", VENV_PY,
                                exists=_exists(VENV_PY), main_python=MAIN)
    assert str(tmp_path / "relworker" / "python") in got.fallback_reason


def test_onnx_providers():
    assert onnx_providers("cuda") == ["CUDAExecutionProvider", "CPUExecutionProvider"]
    assert onnx_providers("cpu") == ["CPUExecutionProvider"]


def test_active_device():
    assert active_device(["CUDAExecutionProvider", "CPUExecutionProvider"]) == "cuda"
    assert active_device(["CPUExecutionProvider"]) == "cpu"
    assert active_device([]) == "cpu"


def test_preload_gpu_libs_calls_when_present_and_tolerates_absence():
    calls = []
    preload_gpu_libs(SimpleNamespace(preload_dlls=lambda: calls.append(1)))
    assert calls == [1]
    preload_gpu_libs(SimpleNamespace())   # older / CPU onnxruntime: no attribute, no error


class _FakeOrt:
    def __init__(self, landed, available=("CPUExecutionProvider",)):
        self.landed = landed
        self.available = list(available)
        self.preloaded = 0
        self.asked = None

    def preload_dlls(self):
        self.preloaded += 1

    def get_available_providers(self):
        return self.available

    def InferenceSession(self, path, providers):  # noqa: N802 - mirrors ORT API
        self.asked = (path, providers)
        return SimpleNamespace(get_providers=lambda: self.landed)


def test_open_session_cuda_lands_on_cuda():
    ort = _FakeOrt(["CUDAExecutionProvider", "CPUExecutionProvider"])
    got = open_onnx_session(ort, "/m.onnx", "cuda")
    assert isinstance(got, OnnxSession)
    assert got.device == "cuda" and got.reason is None
    assert ort.preloaded == 1
    assert ort.asked == ("/m.onnx", ["CUDAExecutionProvider", "CPUExecutionProvider"])


def test_open_session_cuda_silently_lands_on_cpu_is_reported():
    ort = _FakeOrt(["CPUExecutionProvider"], available=["AzureExecutionProvider", "CPUExecutionProvider"])
    got = open_onnx_session(ort, "/m.onnx", "cuda")
    assert got.device == "cpu"
    assert "CUDAExecutionProvider unavailable" in got.reason
    assert "AzureExecutionProvider" in got.reason   # available providers listed for diagnosis


def test_open_session_cpu_does_not_preload():
    ort = _FakeOrt(["CPUExecutionProvider"])
    got = open_onnx_session(ort, "/m.onnx", "cpu")
    assert got.device == "cpu" and got.reason is None and ort.preloaded == 0
