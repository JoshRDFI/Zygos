import pytest
from pydantic import ValidationError

from zygos.runtime.events import (
    CapabilityRenegotiated,
    CapabilityResolved,
    CircuitClosed,
    Event,
    ModelSelected,
    RequestFinished,
    RequestStarted,
    RouteClaimed,
)


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


def test_capability_resolved_payload_validates():
    payload = CapabilityResolved(capability="local_inference", provider="ollama")
    assert payload.type == "capability.resolved"


def test_capability_renegotiated_payload_validates():
    payload = CapabilityRenegotiated(
        capability="local_inference", from_provider="ollama", to_provider="openai"
    )
    assert payload.type == "capability.renegotiated"


def test_capability_payload_forbids_extra_fields():
    with pytest.raises(ValidationError):
        CapabilityResolved(capability="x", provider="y", bogus=1)


def test_event_carries_capability_payload_via_discriminated_union():
    event = Event(
        run_id="r",
        span_id="s",
        source="registry",
        payload=CapabilityResolved(capability="local_inference", provider="ollama"),
    )
    assert event.type == "capability.resolved"


def test_speech_timing_round_trips():
    from zygos.runtime.events import SpeechTiming

    ev = Event(run_id="r", span_id="s", source="speech",
               payload=SpeechTiming(turn_id="t", first_audio_ms=1800, words_at_start=14,
                                    rate_wps=52.0, gaps=1, gap_ms=1300, reason="complete"))
    assert ev.type == "speech.timing"
    again = Event.model_validate(ev.model_dump())
    assert again == ev
    nulls = SpeechTiming(turn_id="t", first_audio_ms=None, words_at_start=None, rate_wps=None,
                         gaps=0, gap_ms=0, reason="error")
    assert Event.model_validate(Event(run_id="r", span_id="s", source="speech",
                                      payload=nulls).model_dump()).payload == nulls


def test_model_fit_round_trips():
    from zygos.runtime.events import ModelFit

    ev = Event(run_id="r", span_id="s", source="models",
               payload=ModelFit(provider="ollama", model="qwen3:8b", level="partial",
                                needs_bytes=9_000, free_bytes=4_000, measured=False))
    assert ev.type == "model.fit"
    assert Event.model_validate(ev.model_dump()) == ev
    unknown = ModelFit(provider="ollama", model="m", level="unknown", needs_bytes=None,
                       free_bytes=None, measured=False)
    assert Event.model_validate(Event(run_id="r", span_id="s", source="models",
                                      payload=unknown).model_dump()).payload == unknown
    with pytest.raises(ValidationError):
        ModelFit(provider="ollama", model="m", level="maybe", needs_bytes=None,
                 free_bytes=None, measured=False)


def test_route_skipped_round_trips():
    from zygos.runtime.events import RouteSkipped

    payload = RouteSkipped(provider="ollama", model="qwen3:8b", reason="no_provider")
    ev = Event(run_id="r", span_id="s", source="router", payload=payload)
    assert ev.type == "route.skipped"
    assert Event.model_validate(ev.model_dump()) == ev


def test_model_loaded_payload_round_trips():
    from zygos.runtime.events import Event, ModelLoaded

    payload = ModelLoaded(provider="ollama", model="qwen3:8b", load_ms=2500, evicted=("gemma4:latest",))
    event = Event(run_id="r", session_id=None, span_id="s", parent_span_id=None, source="models",
                  payload=payload)
    again = Event.model_validate_json(event.model_dump_json())
    assert again.payload == payload
    assert again.payload.type == "model.loaded"
