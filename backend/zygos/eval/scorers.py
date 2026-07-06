"""Scorers — reference-answer gate. Stability: Experimental."""

import re
from typing import Protocol

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
        request = GenerationRequest(
            model=self._judge_model,
            messages=(Message(role="user", content=prompt),),
            temperature=0.0, max_tokens=16,
        )
        reply = (await self._model.generate(ctx, request)).text
        match = _NUM.search(reply)
        if match is None:
            raise ValueError(f"judge returned no parseable score: {reply!r}")
        value = max(0.0, min(1.0, float(match.group())))
        return ScoreResult(score=value, passed=value >= self._threshold,
                           detail=f"llm_judge={value:.2f} model={self._judge_model}")
