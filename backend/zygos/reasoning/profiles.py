"""Reasoning profile parameter sets (shallow/balanced/deep).

Every adaptive/confidence magic number lives here, not in the algorithms.
Stability: Experimental.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedProfile:
    min_iters: int
    max_iters: int
    temperature: float          # base (exploit) temperature
    temperature_explore: float  # warmer temperature when confidence stalls
    max_tokens: int             # base token budget (scaled by complexity)
    early_exit: float           # base adaptive threshold
    floor: float                # threshold floor
    adapt_up: float
    adapt_down: float
    smoothing: float
    fence_band: float           # judge is consulted within +/- this of the threshold
    max_revision_depth: int
    backtrack: bool
    escalate: bool


PROFILES: dict[str, ResolvedProfile] = {
    "shallow": ResolvedProfile(
        min_iters=1, max_iters=2, temperature=0.15, temperature_explore=0.23,
        max_tokens=1024, early_exit=0.78, floor=0.20, adapt_up=0.02, adapt_down=0.04,
        smoothing=0.60, fence_band=0.06, max_revision_depth=1, backtrack=False, escalate=False,
    ),
    "balanced": ResolvedProfile(
        min_iters=1, max_iters=4, temperature=0.20, temperature_explore=0.28,
        max_tokens=2048, early_exit=0.84, floor=0.25, adapt_up=0.03, adapt_down=0.04,
        smoothing=0.55, fence_band=0.05, max_revision_depth=2, backtrack=True, escalate=True,
    ),
    "deep": ResolvedProfile(
        min_iters=2, max_iters=7, temperature=0.22, temperature_explore=0.30,
        max_tokens=4096, early_exit=0.90, floor=0.30, adapt_up=0.04, adapt_down=0.05,
        smoothing=0.50, fence_band=0.04, max_revision_depth=3, backtrack=True, escalate=True,
    ),
}


def resolve_profile(name: str) -> ResolvedProfile:
    return PROFILES[name]
