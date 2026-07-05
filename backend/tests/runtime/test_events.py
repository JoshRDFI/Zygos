import pytest
from pydantic import ValidationError

from zygos.runtime.events import CircuitClosed, Event, RouteClaimed


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
