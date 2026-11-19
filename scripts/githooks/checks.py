#!/usr/bin/env python3
"""Local git hook checks (commit-msg and pre-commit). Stdlib only."""
from __future__ import annotations

import fnmatch
import os
import re
import subprocess
import sys

SUBJECT_RE = re.compile(
    r"^((feat|fix|docs|refactor|test|chore|perf|build|ci|style|revert)(\([^)]+\))?!?: \S"
    r"|Merge |Revert \")"
)
CLAUDE_TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
SUBJECT_HINT = "type(scope): subject  (types: feat fix docs refactor test chore perf build ci style revert)"

PY_TEST_RE = re.compile(r"^\s*(async\s+)?def test_", re.M)
TS_TEST_RE = re.compile(r"^\s*(it|test)(\.each\(.*\))?\(", re.M)
LEFTOVER_RE = re.compile(r"\b(Task \d+|[Rr]uling \d+|[Dd]ecision \d+|this PR)\b|spec\s§")

TEST_GLOBS = (
    "backend/tests/*/test_*.py",
    "backend/tests/test_*.py",
    "scripts/*/test_*.py",
    "scripts/test_*.py",
    "frontend/src/*.test.ts",
    "frontend/src/*.test.tsx",
)
LEFTOVER_PREFIXES = ("backend/zygos/", "frontend/src/", "scripts/")
MIN_SIZE_RATIO = 0.5


def check_message(text: str) -> str | None:
    """Return a failure reason, or None when the message is acceptable."""
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    first = next((ln for ln in lines if ln.strip()), "")
    if not SUBJECT_RE.match(first):
        return f"bad subject line {first!r}; expected: {SUBJECT_HINT}"
    for ln in lines:
        if ln.startswith("Co-Authored-By:") and "Claude" in ln and ln.rstrip() != CLAUDE_TRAILER:
            return f"wrong Claude trailer {ln.strip()!r}; expected exactly: {CLAUDE_TRAILER}"
    return None


def is_test_file(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, g) for g in TEST_GLOBS)


def count_tests(path: str, text: str) -> int:
    rx = PY_TEST_RE if path.endswith(".py") else TS_TEST_RE
    return len(rx.findall(text))


def shrink_problem(path: str, old: str | None, new: str | None, bypass: bool) -> str | None:
    """Compare HEAD (old) and index (new) text of a test file. None means fine."""
    if bypass or old is None:
        return None
    if new is None:
        return f"{path}: test file deleted ({count_tests(path, old)} tests in HEAD)"
    old_n, new_n = count_tests(path, old), count_tests(path, new)
    if new_n < old_n:
        return f"{path}: test count dropped {old_n} -> {new_n}"
    old_b, new_b = len(old.encode()), len(new.encode())
    if new_b < old_b * MIN_SIZE_RATIO:
        return f"{path}: size fell {old_b} -> {new_b} bytes (under 50%; tests {old_n} -> {new_n})"
    return None


def leftover_scope(path: str) -> bool:
    return path.startswith(LEFTOVER_PREFIXES) and not is_test_file(path)


def find_leftovers(path: str, added: list[tuple[int, str]]) -> list[str]:
    return [f"{path}:{n}: {t.strip()}" for n, t in added if LEFTOVER_RE.search(t)]


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def _show(ref: str, path: str) -> str | None:
    r = _git("show", f"{ref}:{path}", check=False)
    return r.stdout if r.returncode == 0 else None


def parse_added(diff: str) -> dict[str, list[tuple[int, str]]]:
    out: dict[str, list[tuple[int, str]]] = {}
    path, line = None, 0
    for ln in diff.splitlines():
        if ln.startswith("+++ "):
            path = ln[6:] if ln.startswith("+++ b/") else None
        elif ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            line = int(m.group(1)) if m else 0
        elif path and ln.startswith("+"):
            out.setdefault(path, []).append((line, ln[1:]))
            line += 1
        elif path and not ln.startswith("-"):
            line += 1
    return out


def run_commit_msg(file: str) -> int:
    with open(file, encoding="utf-8", errors="replace") as fh:
        reason = check_message(fh.read())
    if reason:
        print(f"commit-msg: {reason}", file=sys.stderr)
        print(f"expected subject: {SUBJECT_HINT}\nexpected trailer (if any Claude): {CLAUDE_TRAILER}", file=sys.stderr)
        return 1
    return 0


def run_pre_commit() -> int:
    failed = False
    if _git("diff", "--cached", "--check", check=False).returncode != 0:
        print(_git("diff", "--cached", "--check", check=False).stdout, file=sys.stderr)
        print("pre-commit: git diff --cached --check reported problems", file=sys.stderr)
        failed = True

    bypass = os.environ.get("ZYGOS_ALLOW_TEST_SHRINK") == "1"
    staged = _git("diff", "--cached", "--name-only", "--diff-filter=ACMRD", "-z").stdout.split("\0")
    staged = [p for p in staged if p]
    problems = []
    for p in staged:
        if is_test_file(p):
            prob = shrink_problem(p, _show("HEAD", p), _show("", p), False)
            if prob:
                problems.append(prob)
    if problems and bypass:
        print("pre-commit: ZYGOS_ALLOW_TEST_SHRINK=1 set, test-shrink guard bypassed for:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
    elif problems:
        for p in problems:
            print(f"pre-commit: {p}", file=sys.stderr)
        print("Set ZYGOS_ALLOW_TEST_SHRINK=1 if the reduction is intentional.", file=sys.stderr)
        failed = True

    scoped = [p for p in staged if leftover_scope(p)]
    warnings = []
    if scoped:
        diff = _git("diff", "--cached", "-U0", "--no-color", "--", *scoped).stdout
        for path, added in parse_added(diff).items():
            warnings += find_leftovers(path, added)
    if warnings:
        print("pre-commit warning: planning leftovers in added lines:", file=sys.stderr)
        for w in warnings:
            print(f"  {w}", file=sys.stderr)
        print("tip: comments should make sense without the plan", file=sys.stderr)
    return 1 if failed else 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "commit-msg":
        return run_commit_msg(argv[2])
    if len(argv) == 2 and argv[1] == "pre-commit":
        return run_pre_commit()
    print("usage: checks.py commit-msg <file> | pre-commit", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
