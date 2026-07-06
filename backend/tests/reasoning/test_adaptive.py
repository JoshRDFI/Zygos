import pytest

from zygos.reasoning.adaptive import decide_action, task_complexity, temperature_for, token_budget
from zygos.reasoning.profiles import resolve_profile


def test_complexity_rises_with_markers_and_decomposition():
    simple = task_complexity("hi there", ())
    hard = task_complexity("why compare the tradeoff and analyze each step", ("a", "b", "c", "d", "e", "f"))
    assert hard > simple
    assert 0.0 <= simple <= 1.0 and 0.0 <= hard <= 1.0


def test_temperature_warms_when_stalled():
    p = resolve_profile("balanced")
    assert temperature_for(p, stalled=False) == pytest.approx(p.temperature)
    assert temperature_for(p, stalled=True) == pytest.approx(p.temperature_explore)


def test_token_budget_scales_with_complexity():
    p = resolve_profile("balanced")
    assert token_budget(p, 0.0) < token_budget(p, 1.0)
    assert token_budget(p, 1.0) == p.max_tokens


def test_decide_action_precedence():
    p = resolve_profile("balanced")
    # below min_iters is handled by the caller; here iteration >= min_iters
    assert decide_action(2, p, heuristic_exit=True, judge_exit=None, regressed=False, at_max=False) == "early_exit"
    # in-band: judge overrides heuristic
    assert decide_action(2, p, heuristic_exit=True, judge_exit=False, regressed=False, at_max=False) == "continue"
    assert decide_action(2, p, heuristic_exit=False, judge_exit=True, regressed=False, at_max=False) == "early_exit"
    # regression with backtrack enabled
    assert decide_action(2, p, heuristic_exit=False, judge_exit=None, regressed=True, at_max=False) == "backtrack"
    # at max iterations, stop
    assert decide_action(4, p, heuristic_exit=False, judge_exit=None, regressed=False, at_max=True) == "max_iters"


def test_decide_action_ignores_backtrack_when_profile_disables_it():
    p = resolve_profile("shallow")  # backtrack False
    assert decide_action(2, p, heuristic_exit=False, judge_exit=None, regressed=True, at_max=False) == "continue"
