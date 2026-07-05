"""Runtime event bus and typed event envelope (RFC-0002 §2).

Strictly observational: subscribers observe facts; dropping every subscriber
leaves runtime behavior identical. The payload is a closed discriminated union
of frozen per-event models, validated at construction.

Stability: Experimental.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class EventPayload(BaseModel):
    """Base for per-event-type payloads. Frozen; unknown fields forbidden."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RouteClaimed(EventPayload):
    type: Literal["route.claimed"] = "route.claimed"
    provider: str
    model: str
    probe: bool


class CircuitOpened(EventPayload):
    type: Literal["circuit.opened"] = "circuit.opened"
    provider: str
    model: str
    last_error_code: str


class CircuitClosed(EventPayload):
    type: Literal["circuit.closed"] = "circuit.closed"
    provider: str
    model: str


AnyPayload = Annotated[
    Union[RouteClaimed, CircuitOpened, CircuitClosed],
    Field(discriminator="type"),
]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    session_id: str | None = None
    span_id: str
    parent_span_id: str | None = None
    source: str
    payload: AnyPayload

    @property
    def type(self) -> str:
        return self.payload.type
