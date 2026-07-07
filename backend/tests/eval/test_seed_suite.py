from pathlib import Path

from zygos.eval.suite import load_suite

SEED = Path(__file__).resolve().parents[2] / "zygos/eval/suites/reasoning/reasoning-seed-v1.yaml"


def test_seed_suite_loads_and_is_well_formed():
    suite = load_suite(SEED)
    assert 24 <= len(suite.tasks) <= 36
    categories = {t.category for t in suite.tasks}
    assert categories == {"simple", "standard", "complex_reasoning", "code"}
    splits = {t.split for t in suite.tasks}
    assert splits == {"train", "val"}
    # both splits are non-trivial
    assert len(suite.filter(split="val")) >= 8
    assert len(suite.filter(split="train")) >= 12


def test_every_match_task_declares_expected():
    suite = load_suite(SEED)
    for t in suite.tasks:
        if t.scorer.kind in ("exact_match", "normalized_match"):
            assert t.scorer.expected, f"{t.id} missing expected"
        if t.scorer.kind == "llm_judge":
            assert t.scorer.rubric, f"{t.id} missing rubric"


def test_all_code_tasks_use_code_exec():
    suite = load_suite(SEED)
    code_tasks = [t for t in suite.tasks if t.category == "code"]
    assert code_tasks
    for t in code_tasks:
        assert t.scorer.kind == "code_exec", t.id
        assert t.scorer.checks, t.id
