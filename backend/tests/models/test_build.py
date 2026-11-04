from datetime import datetime, timezone

from zygos.models.build import (
    apply_running,
    kv_bytes_per_token,
    modelfile_num_ctx,
    profile_from_ollama,
    refresh_from_ollama,
)
from zygos.models.profile import ModelProfile, record, resolve
from zygos.providers.types import OllamaModel, OllamaRunning, OllamaShow

T0 = datetime(2026, 11, 4, tzinfo=timezone.utc)
T1 = datetime(2026, 11, 5, tzinfo=timezone.utc)

QWEN3_INFO = {
    "general.architecture": "qwen3",
    "general.parameter_count": 8190735360,
    "qwen3.attention.head_count": 32,
    "qwen3.attention.head_count_kv": 8,
    "qwen3.attention.key_length": 128,
    "qwen3.attention.value_length": 128,
    "qwen3.block_count": 36,
    "qwen3.context_length": 40960,
    "qwen3.embedding_length": 4096,
}


def _model(name="qwen3:8b", **kw):
    base = dict(name=name, size=5225388164, digest="abc", family="qwen3",
                parameter_size="8.2B", quantization_level="Q4_K_M",
                capabilities=("completion", "tools", "thinking"))
    base.update(kw)
    return OllamaModel(**base)


def _show(**kw):
    base = dict(capabilities=("completion", "tools", "thinking"), model_info=QWEN3_INFO,
                parameters='num_ctx 8192\nstop "<|im_end|>"',
                details={"family": "qwen3", "parameter_size": "8.2B", "quantization_level": "Q4_K_M"})
    base.update(kw)
    return OllamaShow(**base)


def test_kv_bytes_per_token_qwen3_8b():
    assert kv_bytes_per_token(QWEN3_INFO) == 147456


def test_kv_bytes_per_token_falls_back_to_embedding_over_heads():
    info = {k: v for k, v in QWEN3_INFO.items() if not k.endswith("key_length")}
    assert kv_bytes_per_token(info) == 147456


def test_kv_bytes_per_token_missing_keys_is_none():
    assert kv_bytes_per_token({}) is None
    assert kv_bytes_per_token({"general.architecture": "x"}) is None
    bad = {**QWEN3_INFO, "qwen3.block_count": "36"}
    assert kv_bytes_per_token(bad) is None
    nohead = {k: v for k, v in QWEN3_INFO.items() if not k.endswith("head_count_kv")}
    assert kv_bytes_per_token(nohead) is None


def test_modelfile_num_ctx():
    assert modelfile_num_ctx('num_ctx 8192\nstop "<|im_end|>"') == 8192
    assert modelfile_num_ctx('stop "x"') is None
    assert modelfile_num_ctx(None) is None


def test_profile_from_ollama_qwen3_8b():
    p = profile_from_ollama(_model(), _show(), at=T0)
    assert (p.provider, p.model, p.names, p.digest) == ("ollama", "qwen3:8b", ["qwen3:8b"], "abc")
    expect = {
        "identity.family": "qwen3",
        "identity.parameter_size": "8.2B",
        "identity.parameter_count": 8190735360,
        "identity.quantization": "Q4_K_M",
        "identity.download_size_bytes": 5225388164,
        "identity.context_length_max": 40960,
        "identity.kv_bytes_per_token": 147456,
        "capabilities.tools": True,
        "capabilities.thinking": True,
        "capabilities.vision": False,
        "capabilities.embedding": False,
        "identity.num_ctx": 8192,
    }
    for key, value in expect.items():
        r = resolve(p, key)
        assert r is not None and r.value == value, key
        assert r.source == ("modelfile" if key == "identity.num_ctx" else "ollama"), key
    assert resolve(p, "identity.specialty") is None


def test_profile_from_ollama_without_show_uses_tags_capabilities():
    p = profile_from_ollama(_model(context_length=4096, capabilities=("completion", "vision")), None, at=T0)
    assert resolve(p, "capabilities.vision").value is True
    assert resolve(p, "capabilities.tools").value is False
    assert resolve(p, "identity.context_length_max").value == 4096
    assert resolve(p, "identity.kv_bytes_per_token") is None
    assert resolve(p, "identity.parameter_count") is None
    assert resolve(p, "identity.num_ctx") is None


def test_profile_without_kv_or_context_still_built():
    show = _show(model_info={"general.architecture": "gemma4"}, parameters=None)
    p = profile_from_ollama(_model("gemma4:e4b", family="gemma4"), show, at=T0)
    assert resolve(p, "identity.context_length_max") is None
    assert resolve(p, "identity.kv_bytes_per_token") is None
    assert resolve(p, "identity.family").value == "gemma4"


def test_specialty_from_name():
    p = profile_from_ollama(_model("qwen2.5-coder:7b-instruct"), _show(), at=T0)
    r = resolve(p, "identity.specialty")
    assert r.value == ["coder", "instruct"] and r.source == "name"
    p2 = profile_from_ollama(_model("Qwen2.5-VL:7b"), None, at=T0)
    assert resolve(p2, "identity.specialty").value == ["vision"]


def test_apply_running_records_measured_vram():
    p = profile_from_ollama(_model(), _show(), at=T0)
    run = OllamaRunning(name="qwen3:8b", digest="abc", size=7000, size_vram=6500, context_length=4096)
    p = apply_running(p, run, at=T1)
    assert resolve(p, "performance.vram_bytes").value == 6500
    assert resolve(p, "performance.loaded_size_bytes").value == 7000
    assert resolve(p, "performance.loaded_context_length").value == 4096
    assert resolve(p, "performance.vram_bytes").source == "measured"
    run2 = OllamaRunning(name="qwen3:8b", digest="abc", size=1, size_vram=1)
    assert resolve(apply_running(p, run2, at=T1), "performance.loaded_context_length").value == 4096


def test_refresh_keeps_measured_and_user():
    p = profile_from_ollama(_model(), _show(), at=T0)
    p = apply_running(p, OllamaRunning(name="qwen3:8b", digest="abc", size=7000, size_vram=6500), at=T0)
    p = p.model_copy(update={"user": {"identity.family": "mine"}})
    p = record(p, "identity.family", 1.5, "eval", T0)
    new = refresh_from_ollama(p, _model(size=999, quantization_level="Q8_0"), _show(parameters=None), at=T1)
    assert resolve(new, "identity.download_size_bytes").value == 999
    assert resolve(new, "identity.quantization").value == "Q8_0"
    assert resolve(new, "performance.vram_bytes").value == 6500
    assert resolve(new, "identity.family").value == "mine"
    assert new.user == {"identity.family": "mine"}
    assert [s for s in new.values["identity.family"] if s.source == "eval"][0].value == 1.5


def test_refresh_drops_a_removed_num_ctx():
    p = profile_from_ollama(_model(), _show(), at=T0)
    assert resolve(p, "identity.num_ctx").value == 8192
    p2 = refresh_from_ollama(p, _model(digest="new"), _show(parameters='stop "<|im_end|>"'), at=T1)
    assert resolve(p2, "identity.num_ctx") is None


def test_kv_bytes_per_token_rejects_bool_values():
    assert kv_bytes_per_token({**QWEN3_INFO, "qwen3.block_count": True}) is None


def test_apply_running_twice_with_same_values_keeps_the_profile_unchanged():
    run = OllamaRunning(name="qwen3:8b", digest="abc", size=6, size_vram=5, context_length=4096)
    p = apply_running(profile_from_ollama(_model(), _show(), at=T0), run, at=T0)
    assert apply_running(p, run, at=T1) == p
    changed = apply_running(p, run.model_copy(update={"size_vram": 7}), at=T1)
    assert resolve(changed, "performance.vram_bytes").at == T1
