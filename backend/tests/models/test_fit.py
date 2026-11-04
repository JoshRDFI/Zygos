from datetime import datetime, timezone

from zygos.hardware.probe import Gpu, HardwareSnapshot
from zygos.models.fit import (
    ASSUMED_CONTEXT_TOKENS,
    RUNTIME_OVERHEAD_BYTES,
    Fit,
    VramContext,
    describe,
    estimate,
    fit,
)
from zygos.models.profile import ModelProfile, record

T0 = datetime(2026, 11, 4, tzinfo=timezone.utc)
GB = 1024**3
DOWNLOAD = 5225388164
KV = 147456
QWEN_TOTAL = DOWNLOAD + KV * 4096 + RUNTIME_OVERHEAD_BYTES  # ~5.93 GB


def _profile(download=DOWNLOAD, kv=KV, num_ctx=None, loaded=None, loaded_ctx=None, vram=None):
    p = ModelProfile(provider="ollama", model="qwen3:8b", names=["qwen3:8b"])
    for key, val, src in [
        ("identity.download_size_bytes", download, "ollama"),
        ("identity.kv_bytes_per_token", kv, "ollama"),
        ("identity.num_ctx", num_ctx, "modelfile"),
        ("performance.loaded_size_bytes", loaded, "measured"),
        ("performance.loaded_context_length", loaded_ctx, "measured"),
        ("performance.vram_bytes", vram, "measured"),
    ]:
        if val is not None:
            p = record(p, key, val, src, T0)
    return p


def _hw(free_gb=None, ram_gb=None, free_bytes=None):
    free = free_bytes if free_bytes is not None else (None if free_gb is None else int(free_gb * GB))
    gpus = None if free is None else (Gpu(name="g", vram_total_bytes=free + GB, vram_free_bytes=free),)
    return HardwareSnapshot(
        gpus=gpus, ram_total_bytes=None, ram_available_bytes=None if ram_gb is None else int(ram_gb * GB),
        cpu_model=None, cpu_cores=None, disk_path=None, disk_free_bytes=None, scanned_at=T0)


def test_estimate_from_parts_qwen3_8b():
    e = estimate(_profile())
    assert e.model_bytes == DOWNLOAD
    assert e.context_bytes == KV * 4096
    assert e.context_tokens == ASSUMED_CONTEXT_TOKENS
    assert e.context_assumed is True
    assert e.overhead_bytes == RUNTIME_OVERHEAD_BYTES
    assert e.total_bytes == QWEN_TOTAL
    assert e.measured is False


def test_estimate_uses_modelfile_num_ctx():
    e = estimate(_profile(num_ctx=8192))
    assert e.context_tokens == 8192
    assert e.context_assumed is False
    assert e.context_bytes == KV * 8192


def test_estimate_measured_replaces_estimate():
    e = estimate(_profile(loaded=6_200_000_000, loaded_ctx=8192))
    assert e.measured is True
    assert e.total_bytes == 6_200_000_000
    assert e.model_bytes == 6_200_000_000
    assert e.context_bytes == 0
    assert e.overhead_bytes == 0
    assert e.context_tokens == 8192


def test_estimate_measured_without_context_length_assumes():
    e = estimate(_profile(loaded=6_200_000_000))
    assert e.context_tokens == ASSUMED_CONTEXT_TOKENS


def test_estimate_unknown_kv_gives_none_total():
    e = estimate(_profile(kv=None))
    assert e.context_bytes is None
    assert e.total_bytes is None
    assert e.model_bytes == DOWNLOAD


def test_fit_gpu():
    f = fit(_profile(), _hw(free_gb=13.7))
    assert f.level == "gpu"
    assert f.vram_available_bytes == int(13.7 * GB)


def test_fit_partial():
    f = fit(_profile(), _hw(free_gb=4, ram_gb=16))
    assert f.level == "partial"


def test_fit_no():
    f = fit(_profile(), _hw(free_gb=2, ram_gb=2))
    assert f.level == "no"


def test_fit_unknown_without_gpu():
    f = fit(_profile(), _hw())
    assert f.level == "unknown"
    assert f.reason == "GPU not detected"
    f2 = fit(_profile(), None)
    assert f2.level == "unknown" and f2.reason == "GPU not detected"


def test_fit_unknown_size_and_context():
    assert fit(_profile(kv=None), _hw(free_gb=13)).reason == "context size unknown"
    f = fit(_profile(download=None), _hw(free_gb=13))
    assert f.level == "unknown" and f.reason == "size unknown"


def test_fit_unknown_when_ram_unknown_and_vram_too_small():
    f = fit(_profile(), _hw(free_gb=2))
    assert f.level == "unknown"
    assert f.reason == "RAM unknown"


def test_fit_counts_reclaimable_and_reserve():
    hw = _hw(free_gb=4, ram_gb=16)
    assert fit(_profile(), hw).level == "partial"
    assert fit(_profile(), hw, VramContext(reclaimable_bytes=3 * GB)).level == "gpu"
    f = fit(_profile(), hw, VramContext(reclaimable_bytes=3 * GB, reserve_bytes=1400 * 1024**2))
    assert f.level == "partial"
    assert f.vram_available_bytes == 4 * GB + 3 * GB - 1400 * 1024**2


def test_fit_floors_available_at_zero():
    f = fit(_profile(), _hw(free_gb=1, ram_gb=16), VramContext(reserve_bytes=5 * GB))
    assert f.vram_available_bytes == 0


def test_fit_loaded_model_adds_back_its_own_vram():
    p = _profile(loaded=6_200_000_000, vram=6_000_000_000)
    assert fit(p, _hw(free_bytes=1_000_000_000, ram_gb=1), loaded=True).level == "gpu"
    p2 = _profile(loaded=6_200_000_000)  # no vram measurement -> nothing added back
    assert fit(p2, _hw(free_bytes=1_000_000_000, ram_gb=1), loaded=True).level == "no"


def test_fit_unloaded_measured_model_gets_no_vram_credit():
    p = _profile(loaded=6_200_000_000, vram=6_000_000_000)  # measured earlier, unloaded since
    f = fit(p, _hw(free_bytes=1_000_000_000, ram_gb=1))
    assert f.needs.measured is True
    assert f.vram_available_bytes == 1_000_000_000
    assert f.level == "no"


def test_describe_estimate_and_measured():
    f = fit(_profile(), _hw(free_gb=13.7))
    assert describe(f) == (
        "needs ≈5.9 GB: 4.9 GB model + 0.6 GB context (4096 tokens, assumed) "
        "+ 0.5 GB overhead; 13.7 GB free"
    )
    f = fit(_profile(num_ctx=8192), _hw(free_gb=13.7))
    assert "(8192 tokens)" in describe(f)
    m = fit(_profile(loaded=int(6.2 * GB)), _hw(free_gb=13.7))
    assert describe(m) == "uses 6.2 GB (measured); 13.7 GB free"


def test_describe_unknown():
    f = fit(_profile(kv=None), _hw(free_gb=13.7))
    assert describe(f) == (
        "needs ≈? GB: 4.9 GB model + context unknown + 0.5 GB overhead; 13.7 GB free"
        " — context size unknown"
    )
    f = fit(_profile(), None)
    assert describe(f) == (
        "needs ≈5.9 GB: 4.9 GB model + 0.6 GB context (4096 tokens, assumed) "
        "+ 0.5 GB overhead — GPU not detected"
    )
    assert isinstance(f, Fit)
