import pytest
from pydantic import ValidationError

from zygos.reasoning.types import (
    AdaptiveDecision, ConfidenceBreakdown, IterationRecord, ReasoningInput,
    ReasoningResult, ReasoningState,
)


def _breakdown() -> ConfidenceBreakdown:
    return ConfidenceBreakdown(
        coherence=0.5, completeness=0.5, consistency=0.9,
        raw_aggregate=0.6, aggregate=0.6, threshold=0.84,
    )


def test_iteration_record_composes():
    rec = IterationRecord(
        index=1, summary="s", confidence=_breakdown(), judge_used=False,
        decision=AdaptiveDecision(temperature=0.2, max_tokens=1024, model="m", action="continue"),
    )
    assert rec.revised_from is None
    assert rec.decision.action == "continue"


def test_reasoning_state_is_frozen():
    state = ReasoningState(
        stage="done", decomposition=("a",), iterations=(), best_iteration=None,
        final_answer="x", halted_early=False, cancelled=False, selected_model="m",
    )
    with pytest.raises(ValidationError):
        state.stage = "recurrent"


def test_action_literal_is_closed():
    with pytest.raises(ValidationError):
        AdaptiveDecision(temperature=0.2, max_tokens=10, model="m", action="teleport")


def test_reasoning_input_defaults_empty_context():
    assert ReasoningInput(prompt="hi").context == ()
