from zygos.reasoning.prompts import (
    build_coda, build_judge, build_prelude, build_recurrent,
    parse_judge, parse_prelude, parse_summary,
)


def test_prelude_prompt_mentions_decomposition_and_prompt():
    p = build_prelude("Explain gravity", ("earlier msg",))
    assert "Explain gravity" in p
    assert "decompos" in p.lower()


def test_recurrent_prompt_includes_prior_and_no_theater():
    p = build_recurrent("Q", ("step one",), "prior summary", 2)
    assert "prior summary" in p
    assert "step one" in p
    # no attention/MoE vocabulary
    for banned in ("mla", "gqa", "expert", "topk", "attention mode"):
        assert banned not in p.lower()


def test_parse_prelude_json():
    summary, decomp = parse_prelude('{"summary": "S", "decomposition": ["a", "b"]}')
    assert summary == "S"
    assert decomp == ("a", "b")


def test_parse_prelude_falls_back_to_raw_text():
    summary, decomp = parse_prelude("not json at all")
    assert summary == "not json at all"
    assert decomp == ()


def test_parse_prelude_brace_slice_fallback():
    summary, decomp = parse_prelude('noise before {"summary": "S", "decomposition": ["a"]} noise after')
    assert summary == "S"
    assert decomp == ("a",)


def test_parse_summary_json_or_raw():
    assert parse_summary('{"summary": "refined"}') == "refined"
    assert parse_summary("just text") == "just text"


def test_parse_judge_extracts_number():
    assert parse_judge('{"confidence": 0.82}') == 0.82
    assert parse_judge("confidence: 0.5") == 0.5
    assert parse_judge("no number here") == 0.0
