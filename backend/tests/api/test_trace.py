import pytest

from zygos.api.frames import TRACE
from zygos.api.session import SessionRegistry
from zygos.api.trace import install_trace_bridge
from zygos.api.turn import TurnDeps, run_turn
from zygos.config.schema import ReasoningConfig
from zygos.providers.fake import FakeProvider
from zygos.reasoning.service import DefaultReasoningService
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import Event, InProcessEventBus
from zygos.runtime.events import RequestStarted  # a live payload type
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


def _registry(bus):
    n = {"i": 0}

    def new_id():
        n["i"] += 1
        return f"s-{n['i']}"

    return SessionRegistry(new_context=lambda sid: root_context(bus, session_id=sid),
                           clock=lambda: 0.0, new_id=new_id)


@pytest.mark.asyncio
async def test_event_delivered_to_matching_connected_session():
    bus = InProcessEventBus()
    reg = _registry(bus)
    install_trace_bridge(bus, reg)
    session = reg.create()
    session.connected = True
    await bus.emit(Event(run_id=session.root.run_id, span_id="span-1", source="reasoning",
                         payload=RequestStarted(prompt_chars=3)))
    frame = session.outbound.get_nowait()
    assert frame.channel == TRACE and frame.type == "event"
    assert frame.payload["type"] == "request.started"


@pytest.mark.asyncio
async def test_event_for_other_run_id_not_delivered():
    bus = InProcessEventBus()
    reg = _registry(bus)
    install_trace_bridge(bus, reg)
    session = reg.create()
    session.connected = True
    await bus.emit(Event(run_id="someone-else", span_id="span-1", source="x", payload=RequestStarted(prompt_chars=1)))
    assert session.outbound.empty()


@pytest.mark.asyncio
async def test_disconnected_session_gets_no_trace():
    bus = InProcessEventBus()
    reg = _registry(bus)
    install_trace_bridge(bus, reg)
    session = reg.create()
    session.connected = False
    await bus.emit(Event(run_id=session.root.run_id, span_id="span-1", source="x", payload=RequestStarted(prompt_chars=1)))
    assert session.outbound.empty()


def _model(bus, text="answer"):
    provider = FakeProvider(text=text)
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    return DefaultModelService(router)


async def _run_reasoning_turn(bus, reg):
    session = reg.create()
    session.connected = True
    model = _model(bus)
    deps = TurnDeps(model_service=model,
                    reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True, profile="shallow")),
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "t1")
    await run_turn(session, deps, "q", CancelToken())
    return [f for f in _all(session) if f.channel == "chat"]


def _all(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


@pytest.mark.asyncio
async def test_dropping_subscriber_leaves_chat_frames_identical():
    # With bridge: chat + trace interleaved. Without: chat only. Chat frames identical.
    bus_with = InProcessEventBus()
    reg_with = _registry(bus_with)
    install_trace_bridge(bus_with, reg_with)
    chat_with = await _run_reasoning_turn(bus_with, reg_with)

    bus_without = InProcessEventBus()
    reg_without = _registry(bus_without)  # no bridge installed
    chat_without = await _run_reasoning_turn(bus_without, reg_without)

    assert [(f.type, f.payload.get("text")) for f in chat_with] == \
           [(f.type, f.payload.get("text")) for f in chat_without]
