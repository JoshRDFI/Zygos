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


# --- hook files must be executable in the index -------------------------------

def test_hook_files_are_executable_in_index():
    import subprocess

    root = Path(__file__).resolve().parents[2]
    out = subprocess.run(
        ["git", "ls-files", "-s", ".githooks"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert out, "no hook files tracked"
    for line in out:
        mode, _sha, _stage_path = line.split(maxsplit=2)
        assert mode == "100755", line


# --- subjects that precede a normal subject -----------------------------------

def test_fixup_squash_amend_prefixes_ok():
    for pre in ("fixup! ", "squash! ", "amend! "):
        assert checks.check_message(f"{pre}feat(api): add thing\n") is None
    assert checks.check_message("fixup! nonsense\n") is not None


# --- shrink guard over name-status entries ------------------------------------

T2 = "def test_a():\n    pass\n\ndef test_b():\n    pass\n"
T1 = "def test_a():\n    pass\n"
T3 = T2 + "\ndef test_c():\n    pass\n"
P = "backend/tests/x/test_a.py"
Q = "backend/tests/x/test_b.py"


def test_parse_name_status():
    raw = "M\0a.py\0R087\0old.py\0new.py\0D\0gone.py\0A\0n.py\0"
    assert checks.parse_name_status(raw) == [
        ("M", "a.py", "a.py"),
        ("R", "old.py", "new.py"),
        ("D", "gone.py", None),
        ("A", None, "n.py"),
    ]


def test_rename_losing_tests_blocked():
    probs = checks.shrink_problems([("R", P, Q, T2, T1)])
    assert len(probs) == 1 and "2 -> 1" in probs[0]


def test_rename_keeping_tests_ok():
    assert checks.shrink_problems([("R", P, Q, T2, T2)]) == []


def test_move_out_of_test_paths_is_deletion():
    probs = checks.shrink_problems([("R", P, "backend/old/test_a.py", T2, T2)])
    assert len(probs) == 1 and "moved out of test paths" in probs[0]


def test_delete_plus_add_with_more_tests_ok():
    assert checks.shrink_problems([("D", P, None, T2, None), ("A", None, Q, None, T3)]) == []


def test_delete_plus_add_with_fewer_tests_blocked():
    probs = checks.shrink_problems([("D", P, None, T2, None), ("A", None, Q, None, T1)])
    assert len(probs) == 1 and "2 -> 1" in probs[0]


def test_plain_delete_blocked_and_nontest_ignored():
    assert len(checks.shrink_problems([("D", P, None, T2, None)])) == 1
    assert checks.shrink_problems([("D", "docs/a.md", None, "x", None)]) == []


def test_modify_still_checked_per_file():
    assert len(checks.shrink_problems([("M", P, P, T2, T1)])) == 1


# --- real git index, in a throwaway repo --------------------------------------

def _repo(tmp_path):
    import subprocess

    def g(*a, **kw):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, check=True, **kw)

    g("init", "-q")
    g("config", "user.email", "t@example.invalid")
    g("config", "user.name", "t")
    return g


def _hook(tmp_path, env=None):
    import os
    import subprocess

    e = {**os.environ, **(env or {})}
    return subprocess.run(
        [sys.executable, str(Path(checks.__file__)), "pre-commit"],
        cwd=tmp_path, capture_output=True, text=True, env=e,
    )


def test_hook_survives_non_utf8_staged_file(tmp_path):
    g = _repo(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "l.py").write_bytes(b"x = 'caf\xe9'  # Task 3\n")
    g("add", ".")
    r = _hook(tmp_path)
    assert r.returncode == 0, r.stderr
    assert "Traceback" not in r.stderr


def test_leftover_scan_failure_cannot_block(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(checks, "_git", boom)
    assert checks.leftover_warnings(["scripts/a.py"]) == ["scan skipped: boom"]


def test_rename_losing_test_blocked_in_real_index(tmp_path):
    g = _repo(tmp_path)
    d = tmp_path / "backend" / "tests" / "x"
    d.mkdir(parents=True)
    (d / "test_a.py").write_text(T2 * 1)
    g("add", ".")
    g("commit", "-qm", "init")
    g("mv", "backend/tests/x/test_a.py", "backend/tests/x/test_b.py")
    (d / "test_b.py").write_text(T2.replace("def test_b", "def helper_b"))
    g("add", ".")
    r = _hook(tmp_path)
    assert r.returncode == 1 and "2 -> 1" in r.stderr


def test_merge_in_progress_skips_shrink(tmp_path):
    g = _repo(tmp_path)
    d = tmp_path / "backend" / "tests" / "x"
    d.mkdir(parents=True)
    (d / "test_a.py").write_text(T2)
    g("add", ".")
    g("commit", "-qm", "init")
    g("rm", "-q", "backend/tests/x/test_a.py")
    assert _hook(tmp_path).returncode == 1
    (tmp_path / ".git" / "MERGE_HEAD").write_text("0" * 40 + "\n")
    r = _hook(tmp_path)
    assert r.returncode == 0 and "merge in progress" in r.stderr
