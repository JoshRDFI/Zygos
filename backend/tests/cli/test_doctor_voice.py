import dataclasses
from types import SimpleNamespace

from zygos.cli.__main__ import render_doctor
from zygos.cli.doctor import DoctorCheck, DoctorReport, parse_gpu, run_doctor
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


async def test_gpu_line_present_when_nvidia_smi_answers(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cpu", alive=False))
    try:
        report = await run_doctor(rt, gpu_query=lambda: "NVIDIA GeForce RTX 5080, 16303, 9371\n")
        c = _check(report, "gpu")
        assert c.ok and c.detail == "NVIDIA GeForce RTX 5080: 16303 MiB total, 9371 MiB free"
    finally:
        await rt.aclose()


async def test_gpu_line_omitted_without_nvidia_smi(tmp_path):
    rt = _runtime_with_voice(tmp_path, TtsHealth(engine="kokoro", device="cpu", alive=False))
    try:
        report = await run_doctor(rt, gpu_query=lambda: None)
        assert not any(c.name == "gpu" for c in report.checks)
    finally:
        await rt.aclose()


def test_parse_gpu_garbage_is_none():
    # Review Focus #4: non-zero exit is None upstream; malformed output is None here.
    assert parse_gpu(None) is None
    assert parse_gpu("") is None
    assert parse_gpu("NVIDIA-SMI has failed because it couldn't communicate with the driver") is None
    assert parse_gpu("RTX, lots, some") is None


def test_parse_gpu_first_gpu_only():
    raw = "GPU A, 100, 50\nGPU B, 200, 150\n"
    assert parse_gpu(raw) == "GPU A: 100 MiB total, 50 MiB free"


async def test_no_voice_checks_when_voice_disabled(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("providers:\n  primary: {provider: fake, model: fake-1}\n")
    rt = build_runtime(cfg)
    try:
        report = await run_doctor(rt, gpu_query=lambda: "X, 1, 1")
        assert not any(c.name.startswith("voice_") or c.name == "gpu" for c in report.checks)
    finally:
        await rt.aclose()


def test_render_marks():
    report = DoctorReport(checks=(DoctorCheck("a", True, "x"),
                                  DoctorCheck("b", True, "y", warn=True),
                                  DoctorCheck("c", False, "z")))
    out = render_doctor(report)
    assert "[ok  ] a" in out and "[warn] b" in out and "[FAIL] c" in out
