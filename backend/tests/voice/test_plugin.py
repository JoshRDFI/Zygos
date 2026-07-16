import sys
from pathlib import Path

import pytest

from zygos.voice.errors import VoiceError
from zygos.voice.plugin import SttPlugin, TtsPlugin
from zygos.voice.types import SttEngineSpec, TtsEngineSpec

FAKE = SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt"))
_SILENT = Path(__file__).parent / "support" / "silent_worker.py"


async def test_start_completes_after_health_ok():
    p = SttPlugin(FAKE, readiness_timeout_s=5.0)
    try:
        await p.start()          # fake worker answers health immediately
        assert p.health().alive is True
    finally:
        await p.aclose()


async def test_start_times_out_when_worker_never_reports_ready():
    spec = SttEngineSpec(name="silent", argv=(sys.executable, str(_SILENT)))
    p = SttPlugin(spec, readiness_timeout_s=0.3)
    with pytest.raises(VoiceError):
        await p.start()
    await p.aclose()


async def test_tts_plugin_start_completes_health_handshake():
    spec = TtsEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_tts"))
    plugin = TtsPlugin(spec, readiness_timeout_s=10.0)
    await plugin.start()
    try:
        assert plugin.health().alive is True
    finally:
        await plugin.aclose()
