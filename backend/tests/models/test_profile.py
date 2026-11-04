from datetime import UTC, datetime

import pytest

from zygos.models.profile import ModelProfile, Sourced, record, resolve, safe_filename

T = datetime(2026, 11, 4, tzinfo=UTC)


def _p(**kw):
    return ModelProfile(provider="ollama", model="qwen3:8b", names=["qwen3:8b"], digest=None, values={}, **kw)


def test_resolve_follows_precedence():
    p = _p()
    for src, v in (("ollama", 1), ("modelfile", 2), ("measured", 3)):
        p = record(p, "performance.x", v, src, T)
    assert resolve(p, "performance.x").value == 3
    p = p.model_copy(update={"user": {"performance.x": 99}})
    r = resolve(p, "performance.x")
    assert (r.value, r.source, r.at) == (99, "user", None)
    assert resolve(p, "nothing.here") is None


def test_record_replaces_same_source_only():
    p = record(_p(), "identity.k", 1, "ollama", T)
    p = record(p, "identity.k", 2, "name", T)
    p2 = record(p, "identity.k", 3, "ollama", T)
    entries = {s.source: s.value for s in p2.values["identity.k"]}
    assert entries == {"ollama": 3, "name": 2}
    assert len(p2.values["identity.k"]) == 2
    assert p.values["identity.k"][0].value == 1  # original untouched


def test_record_refuses_user_source():
    with pytest.raises(ValueError):
        record(_p(), "identity.k", 1, "user", T)


def test_safe_filename_hf_reference():
    assert safe_filename("hf.co/unsloth/Qwen3-8B-GGUF:IQ4_NL") == "hf.co_unsloth_Qwen3-8B-GGUF_IQ4_NL"


def test_safe_filename_ollama_tag():
    assert safe_filename("qwen3:8b") == "qwen3_8b"


def test_sourced_model():
    assert Sourced(value=1, source="eval", at=None).value == 1


def test_record_same_value_keeps_the_original_entry():
    later = datetime(2026, 11, 5, tzinfo=UTC)
    p = record(_p(), "identity.k", 1, "ollama", T)
    assert record(p, "identity.k", 1, "ollama", later) == p
    assert resolve(record(p, "identity.k", 2, "ollama", later), "identity.k").at == later
