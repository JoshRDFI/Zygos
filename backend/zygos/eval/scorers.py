"""Scorers — reference-answer gate. Stability: Experimental."""

import re
from typing import Protocol

from zygos.eval.types import ScoreResult, Task
from zygos.runtime.context import ExecutionContext

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_PUNCT = re.compile(r"[^\w\s]")


class Scorer(Protocol):
    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult: ...


def _normalize(text: str) -> str:
    # strip punctuation, lowercase, collapse whitespace ("" for empty input)
    return " ".join(_PUNCT.sub("", text).lower().split())


class ExactMatchScorer:
    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult:
        expected = (task.scorer.expected or "").strip()
        ok = output.strip() == expected
        return ScoreResult(score=1.0 if ok else 0.0, passed=ok,
                           detail=f"exact_match expected={expected!r}")


class NormalizedMatchScorer:
    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult:
        expected = task.scorer.expected or ""
        tol = task.scorer.tolerance
        if tol is not None:
            want = _NUM.search(expected)
            got = _NUM.search(output)
            if want and got and abs(float(want.group()) - float(got.group())) <= tol:
                return ScoreResult(score=1.0, passed=True,
                                   detail=f"numeric within tol={tol}")
            return ScoreResult(score=0.0, passed=False, detail=f"numeric outside tol={tol}")
        ok = _normalize(expected) == _normalize(output)
        return ScoreResult(score=1.0 if ok else 0.0, passed=ok, detail="normalized_match")


def match_scorers() -> dict[str, Scorer]:
    return {"exact_match": ExactMatchScorer(), "normalized_match": NormalizedMatchScorer()}
