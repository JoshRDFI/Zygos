import pytest

from zygos.reasoning.profiles import PROFILES, resolve_profile


def test_three_profiles_exist_with_ascending_max_iters():
    assert set(PROFILES) == {"shallow", "balanced", "deep"}
    assert PROFILES["shallow"].max_iters == 2
    assert PROFILES["balanced"].max_iters == 4
    assert PROFILES["deep"].max_iters == 7


def test_balanced_values():
    p = resolve_profile("balanced")
    assert p.min_iters == 1
    assert p.early_exit == pytest.approx(0.84)
    assert p.floor == pytest.approx(0.25)
    assert p.smoothing == pytest.approx(0.55)
    assert p.backtrack is True
    assert p.escalate is True


def test_shallow_has_no_backtrack_or_escalate():
    p = resolve_profile("shallow")
    assert p.backtrack is False
    assert p.escalate is False


def test_unknown_profile_raises():
    with pytest.raises(KeyError):
        resolve_profile("turbo")
