"""Real CUDA Kokoro through the managed GPU venv. Run: pytest -m live_gpu"""
import os

import pytest

from zygos.config.schema import TtsConfig
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.device import DEFAULT_GPU_VENV, venv_python
from zygos.voice.service import build_tts_plugin

pytestmark = pytest.mark.live_gpu


@pytest.mark.skipif(not os.path.exists(venv_python(DEFAULT_GPU_VENV)),
                    reason="GPU venv not built (zygos voice setup-gpu)")
async def test_kokoro_synthesizes_on_cuda():
    plugin = build_tts_plugin(TtsConfig(engine="kokoro", device="cuda", readiness_timeout_s=120))
    await plugin.start()
    try:
        h = plugin.health()
        assert (h.device, h.requested_device, h.fallback_reason) == ("cuda", "cuda", None)
        synth = plugin.synthesize(root_context(InProcessEventBus()), "Yes, I can hear you.")
        pcm = b"".join([c async for c in synth.chunks()])
        await synth.aclose()
        assert len(pcm) > 24000   # > 0.5 s of 24 kHz s16 audio
    finally:
        await plugin.aclose()
