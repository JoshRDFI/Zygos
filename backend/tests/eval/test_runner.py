import pytest

from zygos.eval.runner import EvalRunner
from zygos.eval.scorers import match_scorers
from zygos.eval.types import ScorerSpec, Task
from zygos.reasoning.types import ReasoningResult
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class _FakeReasoning:
    def __init__(self, *, text="4", exc: Exception | None = None):
        self._text, self._exc = text, exc

    async def run(self, ctx, input):
        if self._exc is not None:
            raise self._exc
        return ReasoningResult(text=self._text, loops_used=3, final_confidence=0.8,
                               halted_early=True, model="fake-model")


def _make_ctx():
    return root_context(InProcessEventBus())


def _task():
    return Task(id="a", category="simple", split="val", input="2+2?",
                scorer=ScorerSpec(kind="exact_match", expected="4"))


@pytest.mark.asyncio
async def test_run_records_score_and_diagnostics():
    runner = EvalRunner(_FakeReasoning(text="4"), match_scorers(), _make_ctx)
    [rec] = await runner.run([_task()])
    assert rec.passed and rec.score == 1.0
    assert rec.confidence == pytest.approx(0.8) and rec.loops_used == 3
    assert rec.latency_ms is not None and rec.error is None


@pytest.mark.asyncio
async def test_reasoning_failure_is_captured_not_fatal():
    runner = EvalRunner(_FakeReasoning(exc=RuntimeError("provider down")),
                        match_scorers(), _make_ctx)
    [rec] = await runner.run([_task()])
    assert rec.error is not None and "provider down" in rec.error
    assert rec.score is None and rec.passed is None


@pytest.mark.asyncio
async def test_scorer_failure_is_captured():
    # empty scorer map -> lookup raises KeyError -> captured as a scorer error, not fatal
    runner = EvalRunner(_FakeReasoning(text="4"), {}, _make_ctx)
    [rec] = await runner.run([_task()])
    assert rec.error is not None and "scorer" in rec.error and rec.score is None
