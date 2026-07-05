from zygos.runtime.events import Event, InProcessEventBus, RouteClaimed


def _event() -> Event:
    return Event(
        run_id="r", session_id=None, span_id="s", parent_span_id=None,
        source="t", payload=RouteClaimed(provider="p", model="m", probe=False),
    )


async def test_delivers_in_registration_order():
    order: list[str] = []
    bus = InProcessEventBus()

    async def a(_: Event) -> None:
        order.append("a")

    async def b(_: Event) -> None:
        order.append("b")

    bus.subscribe(a)
    bus.subscribe(b)
    await bus.emit(_event())
    assert order == ["a", "b"]


async def test_raising_subscriber_is_isolated():
    seen: list[Event] = []
    bus = InProcessEventBus()

    async def boom(_: Event) -> None:
        raise RuntimeError("subscriber failure")

    async def ok(event: Event) -> None:
        seen.append(event)

    bus.subscribe(boom)
    bus.subscribe(ok)
    await bus.emit(_event())  # must not raise
    assert len(seen) == 1


async def test_zero_subscribers_is_a_noop():
    await InProcessEventBus().emit(_event())  # must not raise
