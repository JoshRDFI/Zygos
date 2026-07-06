import textwrap
import pytest

from zygos.eval.suite import load_suite, SuiteError


def _write(tmp_path, body):
    p = tmp_path / "suite.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_loads_valid_suite_and_filters(tmp_path):
    path = _write(tmp_path, """
        suite: demo
        tasks:
          - id: a
            category: code
            split: val
            input: "write fizzbuzz"
            scorer: {kind: llm_judge, rubric: "correct"}
          - id: b
            category: simple
            split: train
            input: "2+2?"
            scorer: {kind: exact_match, expected: "4"}
    """)
    suite = load_suite(path)
    assert suite.name == "demo"
    assert len(suite.tasks) == 2
    assert [t.id for t in suite.filter(split="val")] == ["a"]
    assert [t.id for t in suite.filter(category="simple")] == ["b"]


def test_rejects_missing_split(tmp_path):
    path = _write(tmp_path, """
        suite: demo
        tasks:
          - id: a
            category: code
            input: "x"
            scorer: {kind: exact_match, expected: "x"}
    """)
    with pytest.raises(SuiteError):
        load_suite(path)


def test_rejects_unknown_category(tmp_path):
    path = _write(tmp_path, """
        suite: demo
        tasks:
          - id: a
            category: poetry
            split: val
            input: "x"
            scorer: {kind: exact_match, expected: "x"}
    """)
    with pytest.raises(SuiteError):
        load_suite(path)


def test_rejects_missing_tasks_key(tmp_path):
    path = tmp_path / "suite.yaml"
    path.write_text("suite: demo\n")
    with pytest.raises(SuiteError):
        load_suite(path)


def test_rejects_missing_scorer(tmp_path):
    path = _write(tmp_path, """
        suite: demo
        tasks:
          - id: a
            category: code
            split: val
            input: "x"
    """)
    with pytest.raises(SuiteError):
        load_suite(path)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(SuiteError):
        load_suite(tmp_path / "does-not-exist.yaml")


def test_rejects_malformed_yaml(tmp_path):
    path = tmp_path / "suite.yaml"
    path.write_text("suite: [unterminated")
    with pytest.raises(SuiteError):
        load_suite(path)


def test_rejects_duplicate_task_ids(tmp_path):
    path = _write(tmp_path, """
        suite: demo
        tasks:
          - id: a
            category: code
            split: val
            input: "x"
            scorer: {kind: exact_match, expected: "x"}
          - id: a
            category: code
            split: train
            input: "y"
            scorer: {kind: exact_match, expected: "y"}
    """)
    with pytest.raises(SuiteError):
        load_suite(path)
