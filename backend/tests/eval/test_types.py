import pytest
from pydantic import ValidationError

from zygos.eval.types import ScorerSpec, Task, ScoreResult, RunRecord


def test_task_is_frozen_and_rejects_unknown_fields():
    task = Task(id="t1", category="code", split="val", input="hi",
                scorer=ScorerSpec(kind="exact_match", expected="hi"))
    assert task.split == "val"
    with pytest.raises(ValidationError):
        Task(id="t1", category="code", split="val", input="hi",
             scorer=ScorerSpec(kind="exact_match"), bogus=1)


def test_task_rejects_unknown_category_and_split():
    with pytest.raises(ValidationError):
        Task(id="t1", category="poetry", split="val", input="hi",
             scorer=ScorerSpec(kind="exact_match"))
    with pytest.raises(ValidationError):
        Task(id="t1", category="code", split="holdout", input="hi",
             scorer=ScorerSpec(kind="exact_match"))


def test_runrecord_allows_null_score_for_errored_task():
    rec = RunRecord(task_id="t1", category="code", split="val", scorer_kind="exact_match",
                    output="", score=None, passed=None, error="boom")
    assert rec.score is None and rec.error == "boom"


def test_score_result_defaults():
    assert ScoreResult(score=1.0, passed=True).detail == ""


def test_task_is_immutable():
    task = Task(id="t1", category="code", split="val", input="hi",
                scorer=ScorerSpec(kind="exact_match", expected="hi"))
    with pytest.raises(ValidationError):
        task.split = "train"


def test_code_exec_requires_checks():
    with pytest.raises(ValidationError):
        ScorerSpec(kind="code_exec")
    with pytest.raises(ValidationError):
        ScorerSpec(kind="code_exec", checks=())


def test_code_exec_spec_holds_checks_and_timeout():
    spec = ScorerSpec(kind="code_exec", checks=("assert f() == 1",), timeout_s=3.0)
    assert spec.checks == ("assert f() == 1",)
    assert spec.timeout_s == 3.0
