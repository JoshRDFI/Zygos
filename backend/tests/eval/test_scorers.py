import pytest

from zygos.eval.scorers import ExactMatchScorer, LlmJudgeScorer, NormalizedMatchScorer
from zygos.eval.types import ScorerSpec, Task
from zygos.providers.types import GenerationRequest, GenerationResult
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


def _task(spec: ScorerSpec) -> Task:
    return Task(id="t", category="simple", split="val", input="q", scorer=spec)


@pytest.mark.asyncio
async def test_exact_match_passes_after_strip():
    t = _task(ScorerSpec(kind="exact_match", expected="4"))
    r = await ExactMatchScorer().score(None, t, "  4\n")
    assert r.passed and r.score == 1.0


@pytest.mark.asyncio
async def test_exact_match_fails_on_difference():
    t = _task(ScorerSpec(kind="exact_match", expected="4"))
    r = await ExactMatchScorer().score(None, t, "four")
    assert not r.passed and r.score == 0.0


@pytest.mark.asyncio
async def test_normalized_match_ignores_case_and_punctuation():
    t = _task(ScorerSpec(kind="normalized_match", expected="Hello, World"))
    r = await NormalizedMatchScorer().score(None, t, "hello world!")
    assert r.passed


@pytest.mark.asyncio
async def test_normalized_match_numeric_tolerance():
    t = _task(ScorerSpec(kind="normalized_match", expected="1157.63", tolerance=0.01))
    r = await NormalizedMatchScorer().score(None, t, "The answer is 1157.63.")
    assert r.passed


@pytest.mark.asyncio
async def test_normalized_match_numeric_outside_tolerance_fails():
    t = _task(ScorerSpec(kind="normalized_match", expected="100", tolerance=0.5))
    r = await NormalizedMatchScorer().score(None, t, "The answer is 200.")
    assert not r.passed


@pytest.mark.asyncio
async def test_normalized_match_parses_clean_numeric_exactly():
    t = _task(ScorerSpec(kind="normalized_match", expected="1157.63", tolerance=0.01))
    r = await NormalizedMatchScorer().score(None, t, "1157.63")
    assert r.passed


class _StubModel:
    def __init__(self, reply: str):
        self._reply = reply
        self.last_request: GenerationRequest | None = None

    async def generate(self, ctx, request: GenerationRequest) -> GenerationResult:
        self.last_request = request
        return GenerationResult(text=self._reply, model=request.model, provider="fake")


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_llm_judge_parses_score_and_uses_judge_model():
    model = _StubModel("0.9")
    scorer = LlmJudgeScorer(model, judge_model="judge-x", pass_threshold=0.6)
    t = _task(ScorerSpec(kind="llm_judge", rubric="correct fizzbuzz"))
    r = await scorer.score(_ctx(), t, "def fizzbuzz(): ...")
    assert r.passed and r.score == pytest.approx(0.9)
    assert model.last_request.model == "judge-x"


@pytest.mark.asyncio
async def test_llm_judge_does_not_cap_tokens():
    # ADR-0006: the judge sends no token cap. A tiny cap starves a thinking judge
    # model (budget spent inside <think>, empty content, no parseable score);
    # None delegates the limit to the provider's policy (uncapped locally).
    model = _StubModel("0.9")
    scorer = LlmJudgeScorer(model, judge_model="judge-x")
    t = _task(ScorerSpec(kind="llm_judge", rubric="correct"))
    await scorer.score(_ctx(), t, "answer")
    assert model.last_request.max_tokens is None


@pytest.mark.asyncio
async def test_llm_judge_below_threshold_fails():
    scorer = LlmJudgeScorer(_StubModel("0.3"), judge_model="judge-x", pass_threshold=0.6)
    t = _task(ScorerSpec(kind="llm_judge", rubric="correct"))
    r = await scorer.score(_ctx(), t, "wrong")
    assert not r.passed and r.score == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_llm_judge_unparseable_reply_raises():
    scorer = LlmJudgeScorer(_StubModel("I cannot decide"), judge_model="judge-x")
    t = _task(ScorerSpec(kind="llm_judge", rubric="correct"))
    with pytest.raises(ValueError):
        await scorer.score(_ctx(), t, "x")


@pytest.mark.asyncio
async def test_llm_judge_clamps_out_of_range_score():
    scorer = LlmJudgeScorer(_StubModel("1.7"), judge_model="judge-x", pass_threshold=0.6)
    t = _task(ScorerSpec(kind="llm_judge", rubric="correct"))
    r = await scorer.score(_ctx(), t, "x")
    assert r.score == 1.0 and r.passed
