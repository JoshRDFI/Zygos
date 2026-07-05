import pytest
from pydantic import ValidationError

from zygos.runtime.events import CircuitClosed, Event, ModelSelected, RequestFinished, RequestStarted, RouteClaimed


def _sample_event() -> Event:
    return Event(
        run_id="r1", session_id=None, span_id="s1", parent_span_id=None,
        source="test", payload=RouteClaimed(provider="p", model="m", probe=False),
    )


def test_event_exposes_payload_type():
    assert _sample_event().type == "route.claimed"


def test_payload_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RouteClaimed(provider="p", model="m", probe=True, bogus=1)


def test_event_rejects_unknown_field():
    with pytest.raises(ValidationError):
        Event(
            run_id="r1", session_id=None, span_id="s1", parent_span_id=None,
            source="test", payload=CircuitClosed(provider="p", model="m"), extra=1,
        )


def test_payloads_are_frozen():
    payload = RouteClaimed(provider="p", model="m", probe=False)
    with pytest.raises(ValidationError):
        payload.provider = "other"


def test_turn_payloads_carry_expected_fields():
    assert RequestStarted(prompt_chars=12).type == "request.started"
    assert RequestFinished(ok=True, loops_used=3).type == "request.finished"
    ms = ModelSelected(provider="ollama", model="qwen3:8b", classification="complex_reasoning")
    assert ms.type == "model.selected" and ms.provider == "ollama"


def test_turn_payloads_are_frozen_and_strict():
    with pytest.raises(ValidationError):
        RequestStarted(prompt_chars=1, extra=2)


def test_event_accepts_turn_payload():
    e = Event(
        run_id="r", session_id=None, span_id="s", parent_span_id=None,
        source="reasoning", payload=RequestStarted(prompt_chars=5),
    )
    assert e.type == "request.started"
