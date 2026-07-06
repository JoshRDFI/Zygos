"""Local, zero-LLM confidence heuristic (ported + cleaned from v1).

coherence  - token-overlap stability vs the prior summary
completeness - size adequacy + decomposition coverage + conclusion marker
consistency  - contradiction/uncertainty penalty
aggregate  - weighted blend, smoothed across iterations
Stability: Experimental.
"""

import re

from zygos.reasoning.profiles import ResolvedProfile
from zygos.reasoning.types import ConfidenceBreakdown

_CONCLUSION = ("therefore", "final", "answer", "conclusion", "thus", "result")
_WEAK = ("maybe", "unsure", "not certain", "unclear")
_CONFLICT = ("however", "but", "on the other hand", "contradict")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def _tokens(text: str) -> set[str]:
    return {t for t in _NON_ALNUM.sub(" ", text.lower()).split() if len(t) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.35
    return len(a & b) / len(a | b)


def _coherence(current: str, prior: str | None) -> float:
    return _clamp(0.45 + _jaccard(_tokens(current), _tokens(prior or "")) * 0.55)


def _decomposition_coverage(current: str, decomposition: tuple[str, ...]) -> float:
    if not decomposition:
        return 1.0
    low = current.lower()
    hits = sum(1 for step in decomposition if step[:24].lower() in low)
    return hits / len(decomposition)


def _completeness(current: str, decomposition: tuple[str, ...]) -> float:
    size = _clamp(min(1.0, len(current) / 220))
    coverage = _decomposition_coverage(current, decomposition)
    low = current.lower()
    conclusion = 0.15 if any(marker in low for marker in _CONCLUSION) else 0.0
    return _clamp(size * 0.5 + coverage * 0.35 + conclusion)


def _consistency(current: str) -> float:
    low = current.lower()
    weak = 0.12 if any(marker in low for marker in _WEAK) else 0.0
    conflict = 0.08 if any(marker in low for marker in _CONFLICT) else 0.0
    return _clamp(1.0 - (weak + conflict))


def _adapt_threshold(
    prev_threshold: float, current_raw: float, prior_aggregate: float | None, profile: ResolvedProfile
) -> float:
    if prior_aggregate is None:
        return profile.early_exit
    if current_raw > prior_aggregate + 0.08:
        return min(0.98, prev_threshold + profile.adapt_up)
    if current_raw < prior_aggregate - 0.08:
        return max(profile.floor, prev_threshold - profile.adapt_down)
    return prev_threshold


def score(
    current: str,
    prior_summary: str | None,
    decomposition: tuple[str, ...],
    prior_aggregate: float | None,
    prev_threshold: float,
    profile: ResolvedProfile,
) -> ConfidenceBreakdown:
    coherence = _coherence(current, prior_summary)
    completeness = _completeness(current, decomposition)
    consistency = _consistency(current)
    raw = _clamp(coherence * 0.4 + completeness * 0.35 + consistency * 0.25)
    if prior_aggregate is None:
        aggregate = raw
    else:
        aggregate = _clamp(prior_aggregate * profile.smoothing + raw * (1 - profile.smoothing))
    threshold = _adapt_threshold(prev_threshold, raw, prior_aggregate, profile)
    return ConfidenceBreakdown(
        coherence=coherence, completeness=completeness, consistency=consistency,
        raw_aggregate=raw, aggregate=aggregate, threshold=threshold,
    )


def in_fence_band(aggregate: float, threshold: float, band: float) -> bool:
    return abs(aggregate - threshold) <= band
