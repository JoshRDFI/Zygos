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
    assert rec.error is not None and "reasoning:" in rec.error and "provider down" in rec.error
    assert rec.score is None and rec.passed is None


@pytest.mark.asyncio
async def test_scorer_failure_is_captured():
    # empty scorer map -> lookup raises KeyError -> captured as a scorer error, not fatal
    runner = EvalRunner(_FakeReasoning(text="4"), {}, _make_ctx)
    [rec] = await runner.run([_task()])
    assert rec.error is not None and "scorer" in rec.error and rec.score is None


class _ScriptedReasoning:
    """Returns/raises per call, in order — lets one task fail and the next succeed."""
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)

    async def run(self, ctx, input):
        item = self._outcomes.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_one_failing_task_does_not_abort_suite():
    ok = ReasoningResult(text="4", loops_used=1, final_confidence=0.5,
                         halted_early=True, model="fake-model")
    reasoning = _ScriptedReasoning([RuntimeError("boom"), ok])
    runner = EvalRunner(reasoning, match_scorers(), _make_ctx)
    recs = await runner.run([_task(), _task()])
    assert len(recs) == 2
    assert recs[0].error is not None and recs[0].score is None
    assert recs[1].error is None and recs[1].passed is True
