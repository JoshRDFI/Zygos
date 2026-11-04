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


def test_fit_without_gpu_says_gpu_not_detected_even_when_size_is_unknown():
    f = fit(_profile(kv=None), _hw())
    assert f.level == "unknown" and f.reason == "GPU not detected; context size unknown"
    f = fit(_profile(download=None), None)
    assert f.level == "unknown" and f.reason == "GPU not detected; size unknown"


# --- llama.cpp: launch-aware estimates (RFC-0014 §4) ---

import pytest  # noqa: E402

from zygos.backends.launch import LaunchSettings  # noqa: E402
from zygos.models.fit import KV_TYPE_BYTES, estimate_llamacpp  # noqa: E402
from zygos.models.profile import resolve  # noqa: E402

MB = 1024**2
LAYER = 100 * MB
OTHER = 500 * MB
KV_LAYER_4096 = 8 * (128 * 2 + 128 * 2) * 4096  # 16 MiB per layer, f16, 4096 tokens


def _lc_profile(blocks=36, layer=LAYER, experts=None, other=OTHER, geometry=True, tensors=True):
    p = ModelProfile(provider="llamacpp", model="m", names=["m"])
    vals = {"identity.download_size_bytes": blocks * layer + other}
    if geometry:
        vals.update({"identity.block_count": blocks, "identity.kv_heads": 8,
                     "identity.key_length": 128, "identity.value_length": 128})
    if tensors:
        vals["identity.tensor_bytes"] = {
            "layers": {str(i): layer for i in range(blocks)},
            "experts": {str(i): experts for i in range(blocks)} if experts else {},
            "other": other}
    for key, val in vals.items():
        p = record(p, key, val, "modelfile", T0)
    return p


def test_kv_type_bytes_exact():
    assert KV_TYPE_BYTES == {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q4_0": 18 / 32,
                             "q4_1": 20 / 32, "q5_0": 22 / 32, "q5_1": 24 / 32, "iq4_nl": 18 / 32}


def test_llamacpp_all_gpu_defaults_are_assumed():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings())
    gpu = 36 * LAYER + OTHER + 36 * KV_LAYER_4096 + RUNTIME_OVERHEAD_BYTES
    assert (e.gpu_bytes, e.cpu_bytes, e.split_by) == (gpu, 0, None)
    assert e.total_bytes == gpu
    assert e.model_bytes == 36 * LAYER + OTHER
    assert e.context_bytes == 36 * KV_LAYER_4096
    assert e.context_tokens == 4096 and e.context_assumed is True
    assert e.measured is False
    assert e.assumptions == ("context 4096 tokens (assumed)",
                             "all layers on GPU (llama-server default assumed)")


def test_llamacpp_explicit_settings_have_no_assumptions():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(ctx_size=8192, n_gpu_layers="all"))
    assert e.assumptions == ()
    assert e.context_tokens == 8192 and e.context_assumed is False
    assert e.context_bytes == 36 * KV_LAYER_4096 * 2
    assert e.split_by is None


def test_llamacpp_ngl_at_or_above_block_count_is_all():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(n_gpu_layers=36))
    assert e.cpu_bytes == 0 and e.split_by is None


def test_llamacpp_ngl_20_of_36_splits_by_settings():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(n_gpu_layers=20))
    assert e.gpu_bytes == 20 * LAYER + 20 * KV_LAYER_4096 + RUNTIME_OVERHEAD_BYTES
    assert e.cpu_bytes == 16 * LAYER + OTHER + 16 * KV_LAYER_4096
    assert e.total_bytes == e.gpu_bytes + e.cpu_bytes
    assert e.split_by == "settings"
    assert e.assumptions == ("context 4096 tokens (assumed)",)


def test_llamacpp_ngl_uses_the_last_layers():
    p = _lc_profile(blocks=4)
    tb = resolve(p, "identity.tensor_bytes").value
    tb = {**tb, "layers": {"0": 1 * MB, "1": 2 * MB, "2": 4 * MB, "3": 8 * MB}}
    p = record(p, "identity.tensor_bytes", tb, "modelfile", T0)
    e = estimate_llamacpp(p, LaunchSettings(n_gpu_layers=1, no_kv_offload=True))
    assert e.gpu_bytes == 8 * MB + RUNTIME_OVERHEAD_BYTES


def test_llamacpp_n_cpu_moe_keeps_first_layers_experts_on_cpu():
    p = _lc_profile(blocks=10, layer=1000 * MB, experts=900 * MB)
    e = estimate_llamacpp(p, LaunchSettings(n_cpu_moe=8, ctx_size=4096))
    assert e.gpu_bytes == 10 * 1000 * MB - 8 * 900 * MB + OTHER + 10 * KV_LAYER_4096 + RUNTIME_OVERHEAD_BYTES
    assert e.cpu_bytes == 8 * 900 * MB
    assert e.split_by == "settings"


def test_llamacpp_n_cpu_moe_ignores_layers_already_on_cpu():
    p = _lc_profile(blocks=10, layer=1000 * MB, experts=900 * MB)
    e = estimate_llamacpp(p, LaunchSettings(n_cpu_moe=8, n_gpu_layers=4, ctx_size=4096))
    # GPU holds layers 6..9; of those only 6 and 7 are among the first 8.
    assert e.gpu_bytes == 4 * 1000 * MB - 2 * 900 * MB + 4 * KV_LAYER_4096 + RUNTIME_OVERHEAD_BYTES
    assert e.cpu_bytes == 6 * 1000 * MB + 2 * 900 * MB + OTHER + 6 * KV_LAYER_4096


def test_llamacpp_quantized_cache_types():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(cache_type_k="q4_0", cache_type_v="q8_0"))
    per_layer = 8 * (128 * 18 / 32 + 128 * 34 / 32) * 4096
    assert e.context_bytes == round(36 * per_layer)


def test_llamacpp_no_kv_offload_puts_all_kv_in_ram():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(n_gpu_layers="all", no_kv_offload=True))
    assert e.gpu_bytes == 36 * LAYER + OTHER + RUNTIME_OVERHEAD_BYTES
    assert e.cpu_bytes == 36 * KV_LAYER_4096
    assert e.split_by == "settings"


def test_llamacpp_unknown_cache_type_is_unknown():
    e = estimate_llamacpp(_lc_profile(), LaunchSettings(cache_type_v="q3_k"))
    assert e.total_bytes is None and e.gpu_bytes is None and e.cpu_bytes is None
    assert e.reason == "unknown cache type q3_k"
    f = fit(_lc_profile(), _hw(free_gb=16, ram_gb=32), needs=e)
    assert f.level == "unknown" and f.reason == "unknown cache type q3_k"


@pytest.mark.parametrize("kw", [{"geometry": False}, {"tensors": False}])
def test_llamacpp_missing_geometry_or_tensors_is_unknown(kw):
    e = estimate_llamacpp(_lc_profile(**kw), LaunchSettings())
    assert e.total_bytes is None and e.split_by is None
    assert fit(_lc_profile(**kw), _hw(free_gb=16, ram_gb=32), needs=e).level == "unknown"


def _split():
    p = _lc_profile()
    return p, estimate_llamacpp(p, LaunchSettings(n_gpu_layers=20))


def test_fit_split_partial_when_each_side_fits():
    p, e = _split()
    f = fit(p, _hw(free_bytes=e.gpu_bytes, ram_gb=32), needs=e)
    assert f.level == "partial"
    assert (f.gpu_bytes, f.cpu_bytes, f.split_by) == (e.gpu_bytes, e.cpu_bytes, "settings")


def test_fit_split_no_when_gpu_side_exceeds_vram_even_if_total_fits():
    p, e = _split()
    f = fit(p, _hw(free_bytes=e.gpu_bytes - 1, ram_gb=64), needs=e)
    assert f.level == "no"


def test_fit_split_no_when_cpu_side_exceeds_ram():
    p, e = _split()
    f = fit(p, _hw(free_gb=24, ram_gb=1), needs=e)
    assert f.level == "no"


def test_fit_split_unknown_when_a_side_is_unknown():
    p, e = _split()
    assert fit(p, _hw(free_gb=24), needs=e).level == "unknown"
    assert fit(p, _hw(free_gb=24), needs=e).reason == "RAM unknown"
    assert fit(p, _hw(ram_gb=64), needs=e).level == "unknown"


def test_fit_unsplit_llamacpp_judged_like_ollama():
    p = _lc_profile()
    e = estimate_llamacpp(p, LaunchSettings())
    assert fit(p, _hw(free_bytes=e.total_bytes, ram_gb=1), needs=e).level == "gpu"
    assert fit(p, _hw(free_bytes=e.total_bytes - 1, ram_gb=1), needs=e).level == "partial"
    assert fit(p, _hw(free_gb=1, ram_gb=1), needs=e).level == "no"
    assert fit(p, _hw(free_gb=1, ram_gb=1), needs=e).split_by is None


def test_existing_fit_has_new_fields_defaulted():
    f = fit(_profile(), _hw(free_gb=16))
    assert (f.gpu_bytes, f.cpu_bytes, f.split_by) == (None, None, None)
    assert f.needs.assumptions == () and f.needs.reason is None


def test_describe_split_exact():
    p, e = _split()
    f = fit(p, _hw(free_gb=8, ram_gb=32), needs=e)
    assert describe(f) == (
        "needs ≈2.8 GB on GPU + 2.3 GB in RAM (split by your settings): "
        "4.0 GB model + 0.6 GB context (4096 tokens, assumed) + 0.5 GB overhead; 8.0 GB free"
        "; assumed: context 4096 tokens (assumed)")


def test_describe_unsplit_llamacpp_exact():
    p = _lc_profile()
    e = estimate_llamacpp(p, LaunchSettings(ctx_size=8192))
    f = fit(p, _hw(free_gb=8, ram_gb=32), needs=e)
    assert describe(f) == (
        "needs ≈5.6 GB: 4.0 GB model + 1.1 GB context (8192 tokens) + 0.5 GB overhead; 8.0 GB free"
        "; assumed: all layers on GPU (llama-server default assumed)")
