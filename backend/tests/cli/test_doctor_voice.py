import dataclasses
from types import SimpleNamespace

from zygos.cli.__main__ import render_doctor
from zygos.cli.doctor import DoctorCheck, DoctorReport, run_doctor
from zygos.runtime.bootstrap import build_runtime
from zygos.voice.contract import SttHealth, TtsHealth


def _runtime_with_voice(tmp_path, tts_health, stt_health=None):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("providers:\n  primary: {provider: fake, model: fake-1}\n")
    rt = build_runtime(cfg)
    stt = stt_health or SttHealth(engine="fake", device="cpu", alive=False)
    snap = SimpleNamespace(stt=stt, tts=tts_health)
    # RuntimeAssembly is a frozen dataclass; aclose() never touches voice_service.
    return dataclasses.replace(rt, voice_service=SimpleNamespace(snapshot=lambda: snap))


def _check(report, name):
    return next(c for c in report.checks if c.name == name)


async def test_voice_device_ok_when_requested_equals_active(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cuda", alive=True,
                                                 requested_device="cuda"))
    try:
        report = await run_doctor(rt, gpu_query=lambda: None)
        c = _check(report, "voice_tts_device")
        assert c.ok and not c.warn and "cuda" in c.detail
        assert _check(report, "voice_stt_device").ok
        assert report.ok
    finally:
        await rt.aclose()


async def test_voice_device_unverified_before_start_is_warn(tmp_path):
    # CLI doctor never calls voice_service.start(); with device: cuda and a venv
    # that exists but is broken (setup-gpu failed, driver/CUDA mismatch, or ORT
    # silently on CPU), the launch-spec device equals requested_device even
    # though nothing has actually confirmed it runs on cuda.
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cuda", alive=False,
                                                 requested_device="cuda"))
    try:
        report = await run_doctor(rt, gpu_query=lambda: None)
        c = _check(report, "voice_tts_device")
        assert c.ok and c.warn
        assert "not verified" in c.detail
        assert "setup-gpu" in c.detail
        assert report.ok                       # warnings never fail doctor
    finally:
        await rt.aclose()


async def test_voice_device_fallback_is_warn_not_fail(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(
        engine="kokoro", device="cpu", alive=False, requested_device="cuda",
        fallback_reason="GPU venv not found at .zygos/venvs/voice-gpu/bin/python; run: zygos voice setup-gpu"))
    try:
        report = await run_doctor(rt, gpu_query=lambda: None)
        c = _check(report, "voice_tts_device")
        assert c.ok and c.warn
        assert "requested cuda" in c.detail and "running on cpu" in c.detail
        assert "zygos voice setup-gpu" in c.detail
        assert report.ok                       # warnings never fail doctor
        assert "[warn]" in render_doctor(report)
    finally:
        await rt.aclose()


async def test_hardware_check_reports_gpu_when_nvidia_smi_answers(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cpu", alive=False))
    try:
        report = await run_doctor(rt, gpu_query=lambda: "NVIDIA GeForce RTX 5080, 16303, 9371\n")
        c = _check(report, "hardware")
        assert c.ok and not c.warn
        assert c.detail.startswith("GPU NVIDIA GeForce RTX 5080: 15.9 GB VRAM, 9.2 GB free · RAM ")
        assert " threads) · disk " in c.detail
        assert not any(x.name == "gpu" for x in report.checks)
    finally:
        await rt.aclose()


async def test_hardware_check_warns_without_nvidia_smi(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cpu", alive=False))
    try:
        report = await run_doctor(rt, gpu_query=lambda: None)
        c = _check(report, "hardware")
        assert c.ok and c.warn
        assert c.detail.startswith("GPU unknown · RAM ")
        assert c.detail.endswith("— GPU not detected: model fit can't be checked")
        assert report.ok
    finally:
        await rt.aclose()


async def test_no_voice_checks_when_voice_disabled(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("providers:\n  primary: {provider: fake, model: fake-1}\n")
    rt = build_runtime(cfg)
    try:
        report = await run_doctor(rt, gpu_query=lambda: "X, 1, 1")
        assert not any(c.name.startswith("voice_") for c in report.checks)
        assert _check(report, "hardware").ok
    finally:
        await rt.aclose()


def test_render_marks():
    report = DoctorReport(checks=(DoctorCheck("a", True, "x"),
                                  DoctorCheck("b", True, "y", warn=True),
                                  DoctorCheck("c", False, "z")))
    out = render_doctor(report)
    assert "[ok  ] a" in out and "[warn] b" in out and "[FAIL] c" in out
