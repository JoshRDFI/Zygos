"""EvalRunner — drives ReasoningService, applies scorers. Stability: Experimental."""

import time
from collections.abc import Callable, Mapping, Sequence

from zygos.eval.scorers import Scorer
from zygos.eval.types import RunRecord, Task
from zygos.reasoning.service import ReasoningService
from zygos.reasoning.types import ReasoningInput
from zygos.runtime.context import ExecutionContext


class EvalRunner:
    def __init__(
        self,
        reasoning: ReasoningService,
        scorers: Mapping[str, Scorer],
        make_context: Callable[[], ExecutionContext],
    ) -> None:
        self._reasoning = reasoning
        self._scorers = scorers
        self._make_context = make_context

    async def run(self, tasks: Sequence[Task]) -> list[RunRecord]:
        records: list[RunRecord] = []
        for task in tasks:
            records.append(await self._run_one(task))
        return records

    async def _run_one(self, task: Task) -> RunRecord:
        base = dict(task_id=task.id, category=task.category, split=task.split,
                    scorer_kind=task.scorer.kind)
        ctx = self._make_context()
        started = time.perf_counter()
        try:
            result = await self._reasoning.run(ctx, ReasoningInput(prompt=task.input))
        except Exception as exc:  # provider/reasoning failure — captured, not fatal
            return RunRecord(**base, output="", score=None, passed=None,
                             error=f"reasoning: {exc}")
        latency_ms = (time.perf_counter() - started) * 1000.0
        try:
            scorer = self._scorers[task.scorer.kind]
            score = await scorer.score(ctx.child("score"), task, result.text)
        except Exception as exc:  # scorer/judge failure — captured, not fatal
            return RunRecord(**base, output=result.text, score=None, passed=None,
                             confidence=result.final_confidence, loops_used=result.loops_used,
                             latency_ms=latency_ms, error=f"scorer: {exc}")
        return RunRecord(**base, output=result.text, score=score.score, passed=score.passed,
                         detail=score.detail, confidence=result.final_confidence,
                         loops_used=result.loops_used, latency_ms=latency_ms)
