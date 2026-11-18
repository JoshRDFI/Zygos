"""Voice defaults resolve against the Zygos data root, never the cwd."""
from pathlib import Path

from zygos.config.schema import SttConfig, TtsConfig
from zygos.home import zygos_home
from zygos.voice import gpu_setup
from zygos.voice.device import venv_python
from zygos.voice.kokoro_assets import resolve_paths
from zygos.voice.service import build_stt_plugin, build_tts_plugin


class _Rec:
    def __call__(self, argv, env=None):
        return 0


def _root() -> Path:
    return zygos_home().root


def test_stt_default_download_root_is_absolute():
    plugin = build_stt_plugin(SttConfig(engine="faster_whisper"))
    assert plugin._spec.env["ZYGOS_STT_DOWNLOAD_ROOT"] == str(_root() / ".zygos/models/faster-whisper")


def test_tts_default_download_root_is_absolute():
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cpu"))
    assert plugin._spec.env["ZYGOS_TTS_DOWNLOAD_ROOT"] == str(_root() / ".zygos/models/kokoro")
    assert "ZYGOS_HOME" not in plugin._spec.env


def test_cuda_uses_root_venv():
    py = Path(venv_python(str(_root() / ".zygos/venvs/voice-gpu")))
    py.parent.mkdir(parents=True)
    py.write_text("")
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda"))
    assert plugin._spec.argv[0] == str(py)
    assert plugin._spec.device == "cuda"


def test_kokoro_assets_default_is_root_based():
    assert resolve_paths(None)[0].parent == _root() / ".zygos/models/kokoro"


def test_setup_gpu_default_venv_is_root_based():
    lines = []
    gpu_setup.setup_gpu(run=_Rec(), exists=lambda p: True, remove=lambda p: None, out=lines.append)
    assert any(str(_root() / ".zygos/venvs/voice-gpu") in ln for ln in lines)
