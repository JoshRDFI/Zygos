import pytest

from zygos.reasoning.confidence import in_fence_band, score
from zygos.reasoning.profiles import resolve_profile


def test_first_iteration_threshold_is_early_exit():
    p = resolve_profile("balanced")
    b = score("Therefore the answer is clearly 42 and complete.", None, (), None, p.early_exit, p)
    assert b.threshold == pytest.approx(p.early_exit)  # no prior -> base threshold
    assert 0.0 <= b.aggregate <= 1.0
    assert b.aggregate == pytest.approx(b.raw_aggregate)  # no smoothing on first


def test_conclusion_marker_lifts_completeness():
    p = resolve_profile("balanced")
    with_concl = score("Therefore the final answer is 42." * 6, None, (), None, p.early_exit, p)
    without = score("The number is 42." * 6, None, (), None, p.early_exit, p)
    assert with_concl.completeness > without.completeness


def test_consistency_penalises_hedging():
    p = resolve_profile("balanced")
    firm = score("The result is 42.", None, (), None, p.early_exit, p)
    hedged = score("Maybe the result is 42, however I am unsure.", None, (), None, p.early_exit, p)
    assert hedged.consistency < firm.consistency


def test_smoothing_blends_with_prior_aggregate():
    p = resolve_profile("balanced")
    b = score("The result is 42.", "The result is 42.", (), 0.9, p.early_exit, p)
    # aggregate is a smoothed blend of prior (0.9) and raw
    assert min(b.raw_aggregate, 0.9) <= b.aggregate <= max(b.raw_aggregate, 0.9)


def test_in_fence_band():
    assert in_fence_band(0.83, 0.84, 0.05) is True
    assert in_fence_band(0.70, 0.84, 0.05) is False
