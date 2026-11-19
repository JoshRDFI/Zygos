import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import checks  # noqa: E402

GOOD = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"


def test_plain_message_ok():
    assert checks.check_message("feat(api): add thing\n\nbody\n") is None


def test_scope_and_bang_ok():
    assert checks.check_message("refactor(core)!: drop old\n") is None


def test_bad_subject_rejected():
    assert checks.check_message("Added a thing\n") is not None
    assert checks.check_message("feat:nospace\n") is not None


def test_merge_and_revert_ok():
    assert checks.check_message("Merge branch 'x'\n") is None
    assert checks.check_message('Revert "feat: x"\n') is None


def test_exact_trailer_ok():
    assert checks.check_message(f"fix: y\n\n{GOOD}\n") is None


def test_wrong_claude_trailer_rejected():
    msg = "fix: y\n\nCo-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>\n"
    reason = checks.check_message(msg)
    assert reason is not None and GOOD in reason


def test_non_claude_coauthor_ok():
    assert checks.check_message("fix: y\n\nCo-Authored-By: Ann <a@b.c>\n") is None


def test_comment_lines_ignored():
    msg = "fix: y\n# Co-Authored-By: Claude Wrong <x@y.z>\n# junk\n"
    assert checks.check_message(msg) is None
    assert checks.check_message("# only comment\nfeat: y\n") is None


PY = "def test_a():\n    pass\n\nasync def test_b():\n    pass\n\nclass T:\n    def test_c(self):\n        pass\n\ndef helper():\n    pass\n"
TS = "it('a', () => {})\n  test('b', () => {})\nit.each([1])('c', () => {})\n  test.each([1])('d', () => {})\ndescribe('x', () => {})\n"


def test_count_python():
    assert checks.count_tests("backend/tests/test_x.py", PY) == 3


def test_count_ts():
    assert checks.count_tests("frontend/src/a.test.tsx", TS) == 4


def test_is_test_file():
    assert checks.is_test_file("backend/tests/api/test_x.py")
    assert checks.is_test_file("scripts/githooks/test_checks.py")
    assert checks.is_test_file("frontend/src/a/b.test.ts")
    assert not checks.is_test_file("backend/zygos/test_x.py")
    assert not checks.is_test_file("backend/tests/conftest.py")


def test_shrink_drop():
    p = checks.shrink_problem("backend/tests/test_x.py", "def test_a():\n pass\ndef test_b():\n pass\n", "def test_a():\n pass\n", False)
    assert p and "test_x.py" in p and "2" in p and "1" in p


def test_shrink_delete():
    assert checks.shrink_problem("backend/tests/test_x.py", "def test_a():\n pass\n", None, False)


def test_shrink_size_under_half():
    old = "def test_a():\n" + "    x = 1\n" * 100
    new = "def test_a():\n    x = 1\n"
    assert checks.shrink_problem("backend/tests/test_x.py", old, new, False)


def test_shrink_new_file_ok():
    assert checks.shrink_problem("backend/tests/test_x.py", None, "def test_a():\n pass\n", False) is None


def test_shrink_growth_ok():
    assert checks.shrink_problem("backend/tests/test_x.py", "def test_a():\n pass\n", "def test_a():\n pass\ndef test_b():\n pass\n", False) is None


def test_shrink_bypass():
    assert checks.shrink_problem("backend/tests/test_x.py", "def test_a():\n pass\n", "", True) is None


def test_leftovers():
    added = [
        (3, "# Task 4 says do this"),
        (4, "x = 1  # see spec §2"),
        (5, "# ruling 3"),
        (6, "# fine comment"),
        (7, "# Decision 9"),
        (8, "# part of this PR"),
    ]
    hits = checks.find_leftovers("backend/zygos/a.py", added)
    assert [h.split(":")[1] for h in hits] == ["3", "4", "5", "7", "8"] or len(hits) == 5


def test_leftover_scope():
    assert checks.leftover_scope("backend/zygos/a.py")
    assert checks.leftover_scope("frontend/src/a.ts")
    assert checks.leftover_scope("scripts/x.py")
    assert not checks.leftover_scope("backend/tests/test_a.py")
    assert not checks.leftover_scope("frontend/src/a.test.ts")
    assert not checks.leftover_scope("docs/a.md")
