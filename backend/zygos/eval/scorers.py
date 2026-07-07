"""Scorers — reference-answer gate. Stability: Experimental."""

import re
from typing import Protocol

from zygos.eval.codeexec import extract_code, run_checks
from zygos.eval.types import ScoreResult, Task
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_PUNCT = re.compile(r"[^\w\s]")


class Scorer(Protocol):
    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult: ...


def _normalize(text: str) -> str:
    # strip punctuation, lowercase, collapse whitespace ("" for empty input)
    return " ".join(_PUNCT.sub("", text).lower().split())


def _parse_number(text: str) -> float | None:
    """Whole-string float first (clean 'number only' output), else first number found."""
    try:
        return float(text.strip())
    except ValueError:
        m = _NUM.search(text)
        return float(m.group()) if m else None


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
            got = _parse_number(output)
            if want is not None and got is not None and abs(float(want.group()) - got) <= tol:
                return ScoreResult(score=1.0, passed=True, detail=f"numeric within tol={tol}")
            return ScoreResult(score=0.0, passed=False, detail=f"numeric outside tol={tol}")
        ok = _normalize(expected) == _normalize(output)
        return ScoreResult(score=1.0 if ok else 0.0, passed=ok, detail="normalized_match")


def match_scorers() -> dict[str, Scorer]:
    return {"exact_match": ExactMatchScorer(), "normalized_match": NormalizedMatchScorer()}


_JUDGE_INSTRUCTIONS = (
    "You are grading an answer. Reply with ONLY a number from 0 to 1 (1 = fully correct).\n"
    "Rubric: {rubric}\n\nTask: {task}\n\nAnswer to grade:\n{output}\n\nScore:"
)


class LlmJudgeScorer:
    def __init__(self, model: ModelService, judge_model: str, pass_threshold: float = 0.6) -> None:
        self._model = model
        self._judge_model = judge_model
        self._threshold = pass_threshold

    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult:
        prompt = _JUDGE_INSTRUCTIONS.format(
            rubric=task.scorer.rubric or "Answer is correct and complete.",
            task=task.input, output=output,
        )
        # No small max_tokens cap: thinking-capable judge models (e.g. qwen3) spend
        # a tiny budget entirely inside their reasoning and return empty content.
        # Use the normal generation budget (GenerationRequest default).
        request = GenerationRequest(
            model=self._judge_model,
            messages=(Message(role="user", content=prompt),),
            temperature=0.0,
        )
        reply = (await self._model.generate(ctx, request)).text
        match = _NUM.search(reply)
        if match is None:
            raise ValueError(f"judge returned no parseable score: {reply!r}")
        value = max(0.0, min(1.0, float(match.group())))
        return ScoreResult(score=value, passed=value >= self._threshold,
                           detail=f"llm_judge={value:.2f} model={self._judge_model}")


class CodeExecScorer:
    async def score(self, ctx: ExecutionContext, task: Task, output: str) -> ScoreResult:
        checks = task.scorer.checks or ()
        outcome = await run_checks(extract_code(output), checks, task.scorer.timeout_s)
        total = outcome.total or 1
        score = outcome.passed / total
        passed = outcome.total > 0 and outcome.passed == outcome.total
        detail = f"code_exec {outcome.passed}/{outcome.total}"
        if outcome.error:
            detail += f" ({outcome.error})"
        return ScoreResult(score=score, passed=passed, detail=detail)
