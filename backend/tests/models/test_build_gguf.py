import os
from datetime import datetime, timezone

import pytest

from zygos.models.build_gguf import LLAMACPP_PROVIDER, QUANT_NAMES, profile_from_gguf
from zygos.models.gguf import GgufHeader, GgufTensor
from zygos.models.gguf_scan import GgufModel
from zygos.models.profile import PRECEDENCE, ModelProfile, record, resolve

T0 = datetime(2026, 11, 4, tzinfo=timezone.utc)
MB = 1024**2


def _meta(**over):
    m = {
        "general.architecture": "qwen3",
        "general.parameter_count": 8_190_735_360,
        "general.file_type": 15,
        "qwen3.context_length": 40960,
        "qwen3.block_count": 2,
        "qwen3.embedding_length": 4096,
        "qwen3.attention.head_count": 32,
        "qwen3.attention.head_count_kv": 8,
        "qwen3.attention.key_length": 128,
        "qwen3.attention.value_length": 96,
    }
    m.update(over)
    return {k: v for k, v in m.items() if v is not None}


def _tensors(experts=False):
    names = [("token_embd.weight", 300 * MB), ("output_norm.weight", 1 * MB), ("output.weight", 200 * MB)]
    for i in range(2):
        names += [(f"blk.{i}.attn_q.weight", 10 * MB), (f"blk.{i}.attn_k.weight", 5 * MB)]
        if experts:
            names += [(f"blk.{i}.ffn_gate_exps.weight", 40 * MB), (f"blk.{i}.ffn_up_exps.weight", 40 * MB),
                      (f"blk.{i}.ffn_down_exps.weight", 40 * MB), (f"blk.{i}.ffn_gate_shexp.weight", 7 * MB)]
        else:
            names += [(f"blk.{i}.ffn_up.weight", 20 * MB)]
    out, off = [], 0
    for name, size in names:
        out.append(GgufTensor(name=name, offset=off, size_bytes=size))
        off += size
    return tuple(out)


def _header(meta=None, experts=False):
    return GgufHeader(version=3, metadata=_meta() if meta is None else meta, tensors=_tensors(experts),
                      data_offset=4096, file_size=4096 + 600 * MB)


def _model(tmp_path, name="Qwen3-8B-Q4_K_M", mmproj=False, parts=1):
    files = []
    for n in range(parts):
        f = tmp_path / f"{name}-{n:05d}.gguf"
        f.write_bytes(b"x" * (10 + n))
        os.utime(f, ns=(1_000_000_000 + n, 1_700_000_000_000_000_000 + n * 1000))
        files.append(f)
    proj = None
    if mmproj:
        proj = tmp_path / "mmproj-f16.gguf"
        proj.write_bytes(b"p")
    return GgufModel(name=name, files=tuple(files), mmproj=proj, size_bytes=sum(f.stat().st_size for f in files))


def _v(p, key):
    s = resolve(p, key)
    return None if s is None else (s.value, s.source)


def test_profile_identity_values_and_sources(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header(), at=T0)
    assert isinstance(p, ModelProfile)
    assert p.provider == LLAMACPP_PROVIDER == "llamacpp"
    assert p.model == "Qwen3-8B-Q4_K_M"
    assert p.names == ["Qwen3-8B-Q4_K_M"]
    assert _v(p, "identity.family") == ("qwen3", "modelfile")
    assert _v(p, "identity.architecture") == ("qwen3", "modelfile")
    assert _v(p, "identity.parameter_count") == (8_190_735_360, "modelfile")
    assert _v(p, "identity.quantization") == ("Q4_K_M", "modelfile")
    assert _v(p, "identity.download_size_bytes") == (10, "modelfile")
    assert _v(p, "identity.context_length_max") == (40960, "modelfile")
    assert _v(p, "identity.block_count") == (2, "modelfile")
    assert _v(p, "identity.kv_heads") == (8, "modelfile")
    assert _v(p, "identity.key_length") == (128, "modelfile")
    assert _v(p, "identity.value_length") == (96, "modelfile")
    assert resolve(p, "capabilities.vision") is None
    assert resolve(p, "identity.specialty") is None


def test_digest_is_size_and_newest_mtime(tmp_path):
    m = _model(tmp_path, parts=2)
    p = profile_from_gguf(m, _header(), at=T0)
    assert p.digest == f"size:{m.size_bytes}:mtime:{1_700_000_000_000_000_000 + 1000}"


def test_kv_per_token_uses_key_and_value_lengths_separately(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header(), at=T0)
    # blocks × kv_heads × (key + value) × f16
    assert _v(p, "identity.kv_bytes_per_token") == (2 * 8 * (128 + 96) * 2, "modelfile")


def test_key_and_value_length_fall_back_to_embedding_over_heads(tmp_path):
    meta = _meta(**{"qwen3.attention.key_length": None, "qwen3.attention.value_length": None})
    p = profile_from_gguf(_model(tmp_path), _header(meta), at=T0)
    assert _v(p, "identity.key_length") == (128, "modelfile")
    assert _v(p, "identity.value_length") == (128, "modelfile")
    assert _v(p, "identity.kv_bytes_per_token") == (2 * 8 * 256 * 2, "modelfile")


def test_missing_geometry_is_not_recorded(tmp_path):
    meta = _meta(**{"qwen3.attention.head_count_kv": None, "general.parameter_count": None})
    p = profile_from_gguf(_model(tmp_path), _header(meta), at=T0)
    assert resolve(p, "identity.kv_heads") is None
    assert resolve(p, "identity.kv_bytes_per_token") is None
    assert resolve(p, "identity.parameter_count") is None


def test_tensor_bytes_dense(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header(), at=T0)
    tb, src = _v(p, "identity.tensor_bytes")
    assert src == "modelfile"
    assert tb == {"layers": {"0": 35 * MB, "1": 35 * MB}, "experts": {}, "other": 501 * MB}


def test_tensor_bytes_moe_counts_experts_inside_layers(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header(experts=True), at=T0)
    tb, _ = _v(p, "identity.tensor_bytes")
    assert tb["layers"] == {"0": 142 * MB, "1": 142 * MB}
    assert tb["experts"] == {"0": 120 * MB, "1": 120 * MB}  # shexp is not an expert tensor
    assert tb["other"] == 501 * MB


@pytest.mark.parametrize("ftype,name", [(0, "F32"), (1, "F16"), (7, "Q8_0"), (15, "Q4_K_M"),
                                        (18, "Q6_K"), (30, "IQ4_XS"), (32, "BF16")])
def test_quantization_known(tmp_path, ftype, name):
    p = profile_from_gguf(_model(tmp_path), _header(_meta(**{"general.file_type": ftype})), at=T0)
    assert _v(p, "identity.quantization") == (name, "modelfile")


@pytest.mark.parametrize("ftype", [4, 99, 1039, "Q4_K_M", None])
def test_quantization_unknown_is_omitted(tmp_path, ftype):
    p = profile_from_gguf(_model(tmp_path), _header(_meta(**{"general.file_type": ftype})), at=T0)
    assert resolve(p, "identity.quantization") is None


def test_quant_table_matches_llama_ftype():
    assert QUANT_NAMES[2] == "Q4_0" and QUANT_NAMES[3] == "Q4_1" and QUANT_NAMES[8] == "Q5_0"
    assert QUANT_NAMES[21] == "Q2_K_S" and QUANT_NAMES[31] == "IQ1_M"
    assert set(QUANT_NAMES) == {0, 1, 2, 3, 7, 8, 9, *range(10, 33)}


def test_specialty_from_name_and_vision_from_mmproj(tmp_path):
    p = profile_from_gguf(_model(tmp_path, name="Qwen2.5-VL-7B-Instruct", mmproj=True), _header(), at=T0)
    assert _v(p, "identity.specialty") == (["instruct", "vision"], "name")
    assert _v(p, "capabilities.vision") == (True, "modelfile")


def test_missing_architecture_records_only_size(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header({}), at=T0)
    assert _v(p, "identity.download_size_bytes") == (10, "modelfile")
    assert resolve(p, "identity.family") is None
    assert resolve(p, "identity.block_count") is None


def test_profile_round_trips_through_json(tmp_path):
    p = profile_from_gguf(_model(tmp_path), _header(experts=True), at=T0)
    again = ModelProfile.model_validate_json(p.model_dump_json())
    tb = resolve(p, "identity.tensor_bytes").value
    assert record(again, "identity.tensor_bytes", tb, "modelfile", T0) is again


def test_server_precedence_sits_after_ollama_before_name():
    assert PRECEDENCE == ("user", "eval", "measured", "modelfile", "ollama", "server", "name")
    p = ModelProfile(provider="llamacpp", model="m")
    p = record(p, "k", 1, "name", T0)
    p = record(p, "k", 2, "server", T0)
    assert resolve(p, "k").value == 2
    p = record(p, "k", 3, "modelfile", T0)
    assert resolve(p, "k").value == 3
