"""Runtime event bus and typed event envelope (RFC-0002 §2).

Strictly observational: subscribers observe facts; dropping every subscriber
leaves runtime behavior identical. The payload is a closed discriminated union
of frozen per-event models, validated at construction.

Stability: Experimental.
"""

from __future__ import annotations

import logging
from typing import Annotated, Awaitable, Callable, Literal, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field


class EventPayload(BaseModel):
    """Base for per-event-type payloads. Frozen; unknown fields forbidden."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class RouteClaimed(EventPayload):
    type: Literal["route.claimed"] = "route.claimed"
    provider: str
    model: str
    probe: bool


class RouteSkipped(EventPayload):
    """A chosen `first` route could not be tried this call (RFC-0013 §5)."""

    type: Literal["route.skipped"] = "route.skipped"
    provider: str
    model: str
    reason: Literal["no_provider", "circuit_open", "rate_limited", "load_failed"]


class CircuitOpened(EventPayload):
    type: Literal["circuit.opened"] = "circuit.opened"
    provider: str
    model: str
    last_error_code: str


class CircuitClosed(EventPayload):
    type: Literal["circuit.closed"] = "circuit.closed"
    provider: str
    model: str


class RequestStarted(EventPayload):
    type: Literal["request.started"] = "request.started"
    prompt_chars: int


class RequestFinished(EventPayload):
    type: Literal["request.finished"] = "request.finished"
    ok: bool
    loops_used: int


class ModelSelected(EventPayload):
    type: Literal["model.selected"] = "model.selected"
    provider: str
    model: str
    classification: str


class ModelChosen(EventPayload):
    """The route a turn pinned at its start, and why (RFC-0013 §5, §11).

    Distinct from ``model.selected`` (the reasoning path's own pick, other fields)."""

    type: Literal["model.chosen"] = "model.chosen"
    turn_id: str
    category: Literal["code", "reasoning", "chat"]
    provider: str
    model: str
    mode: Literal["default"] = "default"
    reason: str


class CapabilityResolved(EventPayload):
    type: Literal["capability.resolved"] = "capability.resolved"
    capability: str
    provider: str


class CapabilityRenegotiated(EventPayload):
    type: Literal["capability.renegotiated"] = "capability.renegotiated"
    capability: str
    from_provider: str
    to_provider: str


class ModelThinking(EventPayload):
    type: Literal["model.thinking"] = "model.thinking"
    turn_id: str
    step: Literal["direct", "tool_loop", "prelude", "recurrent", "judge", "coda"]
    index: int
    text: str
    truncated: bool
    chars: int
    elapsed_ms: int


class SpeechTiming(EventPayload):
    type: Literal["speech.timing"] = "speech.timing"
    turn_id: str
    first_audio_ms: int | None
    words_at_start: int | None
    rate_wps: float | None
    gaps: int
    gap_ms: int
    reason: Literal["complete", "cancelled", "error"]


class ModelFit(EventPayload):
    """Will a local model fit? One per model per catalog view (RFC-0013 §3, §11)."""

    type: Literal["model.fit"] = "model.fit"
    provider: str
    model: str
    level: Literal["gpu", "partial", "no", "unknown"]
    needs_bytes: int | None
    free_bytes: int | None
    measured: bool


class ModelLoaded(EventPayload):
    """Zygos loaded a local model, unloading ``evicted`` to make room (RFC-0013 §8)."""

    type: Literal["model.loaded"] = "model.loaded"
    provider: str
    model: str
    load_ms: int
    evicted: tuple[str, ...]


class McpServerEvent(EventPayload):
    """An MCP server's lifecycle change (RFC-0015). Supervisor events carry a sessionless
    context; a failure during a turn carries that turn's ``run_id``. Never secret values."""

    type: Literal["mcp.server"] = "mcp.server"
    server: str
    kind: Literal["started", "stopped", "restarted", "failed", "listed", "unreachable"]
    detail: str | None = None
    tools: int | None = None


AnyPayload = Annotated[
    Union[
        RouteClaimed,
        RouteSkipped,
        CircuitOpened,
        CircuitClosed,
        RequestStarted,
        RequestFinished,
        ModelSelected,
        ModelChosen,
        CapabilityResolved,
        CapabilityRenegotiated,
        ModelThinking,
        SpeechTiming,
        ModelFit,
        ModelLoaded,
        McpServerEvent,
    ],
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


logger = logging.getLogger("zygos.events")

Subscriber = Callable[[Event], Awaitable[None]]


class EventBus(Protocol):
    def subscribe(self, handler: Subscriber) -> None: ...

    async def emit(self, event: Event) -> None: ...


class InProcessEventBus:
    """Synchronous, in-loop, error-isolated delivery in registration order."""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []

    def subscribe(self, handler: Subscriber) -> None:
        self._subscribers.append(handler)

    async def emit(self, event: Event) -> None:
        for handler in self._subscribers:
            try:
                await handler(event)
            except Exception:  # noqa: BLE001 - isolation is the contract
                logger.exception("event subscriber raised; isolated (type=%s)", event.type)
