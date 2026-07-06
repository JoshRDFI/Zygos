import pytest

from zygos.eval.scorers import ExactMatchScorer, NormalizedMatchScorer
from zygos.eval.types import ScorerSpec, Task


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
