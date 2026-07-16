"""Live RFC-0005 AC1 proof: real faster-whisper transcribes a known clip on CPU.

Excluded by default (`live_voice` marker). Run explicitly with the voice extra
installed and the model provisioned:
    cd backend && .venv/bin/python -m pytest -m live_voice -v
"""
import sys
import wave
from pathlib import Path

import pytest

from zygos.voice.plugin import SttPlugin, Transcription
from zygos.voice.types import SttEngineSpec

pytestmark = pytest.mark.live_voice

FIXTURE = Path(__file__).parent / "fixtures" / "hello.wav"
# distinctive words known to appear in the fixture clip (lower-cased, punctuation-free);
# the test passes if ANY appear, so it tolerates minor ASR variation.
EXPECTED_WORDS = {"speculative", "asset", "hopeful", "purchasing", "power", "retain"}


def _read_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1 and w.getsampwidth() == 2
        return w.readframes(w.getnframes())


async def test_faster_whisper_transcribes_known_clip():
    spec = SttEngineSpec(
        name="faster_whisper",
        argv=(sys.executable, "-m", "zygos.voice.sidecar.faster_whisper"),
        env={"ZYGOS_STT_MODEL": "base.en", "ZYGOS_STT_DEVICE": "cpu",
             "ZYGOS_STT_COMPUTE_TYPE": "int8"},
    )
    plugin = SttPlugin(spec, readiness_timeout_s=120.0)  # generous for first-run load
    await plugin.start()
    try:
        tr = Transcription(plugin._handle.connection)
        pcm = _read_pcm(FIXTURE)
        for i in range(0, len(pcm), 3200):     # ~100 ms chunks
            await tr.push(pcm[i:i + 3200])
        await tr.endpoint()
        finals = [ev async for ev in tr.events() if ev.kind == "final"]
        assert finals, "no final transcript"
        got = {w.strip(".,!?").lower() for w in finals[-1].text.split()}
        assert EXPECTED_WORDS & got, f"expected some of {EXPECTED_WORDS}, got {finals[-1].text!r}"
    finally:
        await plugin.aclose()
