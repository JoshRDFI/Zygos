import logging
import sys
from pathlib import Path

import pytest

from zygos.config.schema import TtsConfig
from zygos.voice.errors import VoiceError
from zygos.voice.plugin import TtsPlugin
from zygos.voice.service import build_tts_plugin
from zygos.voice.types import TtsEngineSpec

_SUPPORT = Path(__file__).parent / "support"
FAKE = TtsEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_tts"))
SILENT = TtsEngineSpec(name="kokoro", device="cuda",
                       argv=(sys.executable, str(_SUPPORT / "silent_worker.py")))
CPU_FALLBACK = TtsEngineSpec(name="kokoro", device="cpu",
                             argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_tts"))


def _device_spec(device, reason=None, spec_device="cuda"):
    env = {"ZYGOS_TEST_DEVICE": device}
    if reason:
        env["ZYGOS_TEST_REASON"] = reason
    return TtsEngineSpec(name="kokoro", device=spec_device, env=env,
                         argv=(sys.executable, str(_SUPPORT / "device_worker.py")))


async def test_old_style_health_ok_falls_back_to_spec_device():
    # Review Focus #1: fake_tts replies {"type":"health_ok"} with no device.
    p = TtsPlugin(FAKE, readiness_timeout_s=5.0)
    try:
        await p.start()
        h = p.health()
        assert (h.device, h.requested_device, h.fallback_reason) == ("cpu", "cpu", None)
    finally:
        await p.aclose()


async def test_worker_reported_device_is_active():
    p = TtsPlugin(_device_spec("cuda"), readiness_timeout_s=5.0)
    try:
        await p.start()
        h = p.health()
        assert (h.device, h.requested_device, h.fallback_reason) == ("cuda", "cuda", None)
    finally:
        await p.aclose()


async def test_worker_reported_cpu_fallback_reason(caplog):
    p = TtsPlugin(_device_spec("cpu", reason="CUDAExecutionProvider unavailable"),
                  readiness_timeout_s=5.0)
    try:
        with caplog.at_level(logging.WARNING):
            await p.start()
        h = p.health()
        assert (h.device, h.requested_device) == ("cpu", "cuda")
        assert "CUDAExecutionProvider unavailable" in h.fallback_reason
        assert any("CUDAExecutionProvider unavailable" in r.getMessage() for r in caplog.records)
    finally:
        await p.aclose()


async def test_gpu_readiness_failure_retries_on_cpu_fallback():
    p = TtsPlugin(SILENT, readiness_timeout_s=0.3, fallback_spec=CPU_FALLBACK)
    try:
        await p.start()
        h = p.health()
        assert h.alive is True
        assert (h.device, h.requested_device) == ("cpu", "cuda")
        assert h.fallback_reason.startswith("GPU worker failed to start:")
        assert p._spec is CPU_FALLBACK        # crash restarts will reuse the winner
    finally:
        await p.aclose()


async def test_no_fallback_spec_raises():
    p = TtsPlugin(SILENT, readiness_timeout_s=0.3)
    with pytest.raises(VoiceError):
        await p.start()
    await p.aclose()


async def test_both_attempts_fail_raises_and_closes_both():
    # Review Focus #3
    silent_cpu = TtsEngineSpec(name="kokoro", device="cpu",
                               argv=(sys.executable, str(_SUPPORT / "silent_worker.py")))
    p = TtsPlugin(SILENT, readiness_timeout_s=0.3, fallback_spec=silent_cpu)
    first_handle = p._handle
    with pytest.raises(VoiceError):
        await p.start()
    assert first_handle._closed is True
    await p.aclose()
    assert p._handle._closed is True


async def test_launch_reason_takes_precedence_over_worker_reason():
    p = TtsPlugin(_device_spec("cpu", reason="worker says cpu", spec_device="cpu"),
                  readiness_timeout_s=5.0, requested_device="cuda",
                  launch_reason="GPU venv not found at X")
    try:
        await p.start()
        assert p.health().fallback_reason == "GPU venv not found at X"
    finally:
        await p.aclose()


async def test_retry_reason_takes_precedence_over_worker_reason():
    fb = _device_spec("cpu", reason="worker says cpu", spec_device="cpu")
    p = TtsPlugin(SILENT, readiness_timeout_s=0.3, fallback_spec=fb)
    try:
        await p.start()
        assert p.health().fallback_reason.startswith("GPU worker failed to start:")
    finally:
        await p.aclose()


async def test_health_before_start_reports_launch_state():
    p = TtsPlugin(CPU_FALLBACK, requested_device="cuda", launch_reason="GPU venv not found at X")
    h = p.health()
    assert (h.device, h.requested_device, h.fallback_reason) == ("cpu", "cuda", "GPU venv not found at X")
