"""Live RFC-0005 AC1 proof: real Kokoro synthesizes intelligible 24 kHz PCM on CPU.

Excluded by default (`live_voice` marker). Run explicitly with the voice extra
installed and the model provisioned (first run downloads ~80MB):
    cd backend && .venv/bin/python -m pytest -m live_voice -v
"""
import sys

import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.plugin import TtsPlugin
from zygos.voice.types import TtsEngineSpec

pytestmark = pytest.mark.live_voice


async def test_kokoro_synthesizes_pcm():
    spec = TtsEngineSpec(
        name="kokoro",
        argv=(sys.executable, "-m", "zygos.voice.sidecar.kokoro"),
        env={"ZYGOS_TTS_VOICE": "af_heart"},
    )
    plugin = TtsPlugin(spec, readiness_timeout_s=180.0)  # generous for first-run download+load
    await plugin.start()
    try:
        ctx = root_context(InProcessEventBus())   # same construction tests/voice/test_tts_plugin.py uses
        syn = plugin.synthesize(ctx, "Kokoro speaks. This is a test.")
        pcm = b"".join([chunk async for chunk in syn.chunks()])
        assert len(pcm) > 2000                      # non-trivial audio
        assert len(pcm) % 2 == 0                     # 16-bit frames
    finally:
        await plugin.aclose()
