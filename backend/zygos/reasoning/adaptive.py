"""Adaptive-compute decisions — the real replacement for v1's attention/MoE theater.

Every function is pure and returns a real knob (temperature, tokens) or a control
decision that actually changes the reasoning loop. Stability: Experimental.
"""

import re

from zygos.reasoning.profiles import ResolvedProfile

_MARKERS = ("why", "because", "compare", "tradeoff", "trade-off", "analyze", "multi", "step")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def task_complexity(prompt: str, decomposition: tuple[str, ...]) -> float:
    low = prompt.lower()
    present = sum(1 for marker in _MARKERS if marker in low)
    marker_score = present / len(_MARKERS)
    decomposition_score = min(1.0, len(decomposition) / 6)
    length_score = min(1.0, len(prompt) / 500)
    return _clamp(marker_score * 0.4 + decomposition_score * 0.35 + length_score * 0.25)


def temperature_for(profile: ResolvedProfile, stalled: bool) -> float:
    return profile.temperature_explore if stalled else profile.temperature


def token_budget(profile: ResolvedProfile, complexity: float) -> int:
    return int(profile.max_tokens * (0.5 + 0.5 * _clamp(complexity)))


def decide_action(
    iteration: int,
    profile: ResolvedProfile,
    heuristic_exit: bool,
    judge_exit: bool | None,
    regressed: bool,
    at_max: bool,
) -> str:
    """Decide the recurrent-loop action. `judge_exit` is None when the confidence was
    outside the fence band (no judge consulted); otherwise it overrides the heuristic."""
    exit_now = judge_exit if judge_exit is not None else heuristic_exit
    if exit_now:
        return "early_exit"
    if regressed and profile.backtrack:
        return "backtrack"
    if at_max:
        return "max_iters"
    return "continue"
