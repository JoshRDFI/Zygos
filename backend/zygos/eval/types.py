"""Eval data models — frozen contracts, no logic. Stability: Experimental."""

from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, model_validator

Category = Literal["simple", "standard", "complex_reasoning", "code"]
Split = Literal["train", "val"]
ScorerKind = Literal["exact_match", "normalized_match", "llm_judge", "code_exec"]


class ScorerSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: ScorerKind
    expected: str | None = None      # match scorers
    tolerance: float | None = None   # numeric tolerance for normalized_match
    rubric: str | None = None        # llm_judge
    checks: tuple[str, ...] | None = None   # code_exec: assert snippets
    timeout_s: float | None = None          # code_exec: per-task wall-clock budget

    @model_validator(mode="after")
    def _require_checks_for_code_exec(self) -> "ScorerSpec":
        if self.kind == "code_exec" and not self.checks:
            raise ValueError("code_exec scorer requires a non-empty 'checks' list")
        return self


class Task(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    category: Category
    split: Split
    input: str
    scorer: ScorerSpec


class ScoreResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    score: float          # 0..1
    passed: bool
    detail: str = ""


class RunRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: str
    category: Category
    split: Split
    scorer_kind: str
    output: str
    score: float | None
    passed: bool | None
    detail: str = ""
    confidence: float | None = None   # diagnostic: ReasoningResult.final_confidence
    loops_used: int | None = None
    latency_ms: float | None = None
    error: str | None = None


class SplitSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    n: int          # scored (non-errored) tasks
    errors: int
    mean_score: float
    pass_rate: float


class EvalReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    suite: str
    records: tuple[RunRecord, ...]
    by_split: Mapping[str, SplitSummary]
    by_category: Mapping[str, SplitSummary]
    by_scorer: Mapping[str, SplitSummary]
    errors: int
