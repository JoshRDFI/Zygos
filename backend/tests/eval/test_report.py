from zygos.eval.report import build_report, render_table
from zygos.eval.types import RunRecord


def _rec(**kw):
    base = dict(task_id="t", category="simple", split="val", scorer_kind="exact_match",
                output="o", score=1.0, passed=True)
    base.update(kw)
    return RunRecord(**base)


def test_build_report_splits_and_excludes_errors():
    records = [
        _rec(task_id="a", split="val", score=1.0, passed=True),
        _rec(task_id="b", split="val", score=0.0, passed=False),
        _rec(task_id="c", split="val", score=None, passed=None, error="boom"),
        _rec(task_id="d", split="train", score=1.0, passed=True),
    ]
    report = build_report("demo", records)
    val = report.by_split["val"]
    assert val.n == 2 and val.errors == 1
    assert val.mean_score == 0.5 and val.pass_rate == 0.5
    assert report.errors == 1
    assert report.by_split["train"].mean_score == 1.0


def test_by_category_aggregation():
    records = [
        _rec(task_id="a", category="code", score=1.0, passed=True),
        _rec(task_id="b", category="simple", score=0.0, passed=False),
    ]
    report = build_report("demo", records)
    assert report.by_category["code"].pass_rate == 1.0
    assert report.by_category["simple"].pass_rate == 0.0


def test_render_table_is_nonempty_string():
    report = build_report("demo", [_rec()])
    text = render_table(report)
    assert "demo" in text and "val" in text


def test_by_scorer_aggregation():
    records = [
        _rec(task_id="a", scorer_kind="exact_match", score=1.0, passed=True),
        _rec(task_id="b", scorer_kind="llm_judge", score=0.0, passed=False),
    ]
    report = build_report("demo", records)
    assert report.by_scorer["exact_match"].pass_rate == 1.0
    assert report.by_scorer["llm_judge"].pass_rate == 0.0
