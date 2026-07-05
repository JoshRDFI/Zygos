from zygos.runtime.context import ExecutionContext, root_context
from zygos.runtime.events import Event, InProcessEventBus, RouteClaimed


def _recorder():
    events: list[Event] = []

    async def sub(event: Event) -> None:
        events.append(event)

    return events, sub


def test_root_context_mints_distinct_ids():
    ctx = root_context(InProcessEventBus())
    assert ctx.run_id and ctx.span_id
    assert ctx.run_id != ctx.span_id
    assert ctx.parent_span_id is None
    assert ctx.cancelled is False


def test_child_preserves_span_chain():
    ctx = root_context(InProcessEventBus())
    child = ctx.child("span-2")
    assert child.span_id == "span-2"
    assert child.parent_span_id == ctx.span_id
    assert child.run_id == ctx.run_id
    assert isinstance(child, ExecutionContext)


async def test_emit_stamps_correlation_ids():
    events, sub = _recorder()
    bus = InProcessEventBus()
    bus.subscribe(sub)
    ctx = root_context(bus, session_id="sess-1")
    await ctx.emit(RouteClaimed(provider="p", model="m", probe=False), source="unit")
    assert len(events) == 1
    event = events[0]
    assert event.run_id == ctx.run_id
    assert event.span_id == ctx.span_id
    assert event.session_id == "sess-1"
    assert event.source == "unit"
    assert event.type == "route.claimed"


async def test_cancel_token_trips():
    ctx = root_context(InProcessEventBus())
    assert ctx.cancelled is False
    ctx._cancel.trip()
    assert ctx.cancelled is True
