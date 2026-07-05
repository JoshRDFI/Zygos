"""Reasoning data models (RFC-0001 §4 snapshotable state). Stability: Experimental."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ReasoningInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    prompt: str
    context: tuple[str, ...] = ()


class ConfidenceBreakdown(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    coherence: float
    completeness: float
    consistency: float
    raw_aggregate: float
    aggregate: float           # smoothed
    threshold: float           # adaptive threshold applied at this iteration


class AdaptiveDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    temperature: float
    max_tokens: int
    model: str
    action: Literal["continue", "early_exit", "backtrack", "max_iters"]


class IterationRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    index: int
    summary: str
    confidence: ConfidenceBreakdown
    judge_used: bool
    decision: AdaptiveDecision
    revised_from: int | None = None


class ReasoningState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["idle", "prelude", "recurrent", "coda", "done", "cancelled"]
    decomposition: tuple[str, ...]
    iterations: tuple[IterationRecord, ...]
    best_iteration: int | None
    final_answer: str | None
    halted_early: bool
    cancelled: bool
    selected_model: str | None


class ReasoningResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    loops_used: int
    final_confidence: float
    halted_early: bool
    model: str
