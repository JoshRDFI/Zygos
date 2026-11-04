import pytest

from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus, ModelThinking
from zygos.thinking.capture import MAX_THINKING_EVENT_CHARS, TailBuffer, ThinkingRecorder


def test_tail_buffer_under_cap_keeps_all():
    b = TailBuffer()
    b.append("hello ")
    b.append("world")
    assert b.text == "hello world" and b.chars == 11 and b.truncated is False


def test_tail_buffer_keeps_exact_tail():
    b = TailBuffer(32_000)
    b.append("a" * 20_000)
    b.append("b" * 20_000)
    assert b.text == "a" * 12_000 + "b" * 20_000
    assert b.chars == 40_000 and b.truncated is True


def test_tail_buffer_memory_bounded():
    b = TailBuffer()
    for _ in range(1_000):
        b.append("x" * 1_000)
        assert len(b.text) <= MAX_THINKING_EVENT_CHARS
    assert len(b.text) == 32_000


class _Capture:
    def __init__(self):
        self.events = []

    async def __call__(self, event):
        self.events.append(event)


def _ctx():
    bus = InProcessEventBus()
    cap = _Capture()
    bus.subscribe(cap)
    return root_context(bus, session_id="s"), cap


@pytest.mark.asyncio
async def test_recorder_emits_event():
    ctx, cap = _ctx()
    await ThinkingRecorder("t1").record(ctx, step="tool_loop", index=2, text="x", elapsed_ms=150)
    assert len(cap.events) == 1
    assert cap.events[0].source == "thinking"
    assert cap.events[0].payload == ModelThinking(
        turn_id="t1", step="tool_loop", index=2, text="x", truncated=False, chars=1, elapsed_ms=150)


@pytest.mark.asyncio
async def test_recorder_skips_empty():
    ctx, cap = _ctx()
    r = ThinkingRecorder("t1")
    await r.record(ctx, step="direct", index=0, text=None, elapsed_ms=5)
    await r.record(ctx, step="direct", index=0, text="", elapsed_ms=5)
    assert cap.events == [] and r.total_ms is None


@pytest.mark.asyncio
async def test_recorder_total_ms_sums():
    ctx, _ = _ctx()
    r = ThinkingRecorder("t1")
    await r.record(ctx, step="prelude", index=0, text="a", elapsed_ms=100)
    await r.record(ctx, step="coda", index=1, text="b", elapsed_ms=250)
    assert r.total_ms == 350


@pytest.mark.asyncio
async def test_recorder_accepts_prefilled_buffer():
    ctx, cap = _ctx()
    rec = ThinkingRecorder("t1")
    await rec.record(ctx, step="direct", index=0, text=TailBuffer(), elapsed_ms=5)
    assert cap.events == [] and rec.total_ms is None  # empty buffer: nothing recorded
    buf = TailBuffer()
    for _ in range(40):
        buf.append("y" * 1_000)
    await rec.record(ctx, step="direct", index=0, text=buf, elapsed_ms=5)
    (ev,) = cap.events
    assert len(ev.payload.text) == 32_000 and ev.payload.chars == 40_000
    assert ev.payload.truncated is True
