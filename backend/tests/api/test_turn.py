import pytest

from zygos.api.frames import CHAT
from zygos.api.session import Session
from zygos.api.turn import TurnDeps, build_messages, format_exchange, run_turn
from zygos.config.schema import ReasoningConfig
from zygos.providers.fake import FakeProvider
from zygos.reasoning.service import DefaultReasoningService
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice


def _session(bus=None):
    bus = bus or InProcessEventBus()
    return Session("s1", root_context(bus, session_id="s1"), created_at=0.0)


def _model(script=None, text="fake response"):
    provider = FakeProvider(script=script, text=text)
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    return DefaultModelService(router)


def _deps(model=None, *, reasoning=False, memory=None):
    model = model or _model()
    return TurnDeps(
        model_service=model,
        reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True, profile="shallow")),
        reasoning_enabled=reasoning,
        memory_service=memory,
        new_id=lambda: "turn-1",
    )


def _drain(session):
    frames = []
    while not session.outbound.empty():
        frames.append(session.outbound.get_nowait())
    return frames


def test_build_messages_omits_system_when_no_context():
    msgs = build_messages((), "hello")
    assert [m.role for m in msgs] == ["user"]
    assert msgs[-1].content == "hello"


def test_build_messages_includes_memory_system_message():
    msgs = build_messages(("fact A", "fact B"), "hello")
    assert msgs[0].role == "system"
    assert "fact A" in msgs[0].content and "fact B" in msgs[0].content
    assert msgs[-1].role == "user"


@pytest.mark.asyncio
async def test_reasoning_off_streams_tokens_then_turn_end():
    session = _session()
    await run_turn(session, _deps(_model(script=["alpha beta gamma"])), "hi", CancelToken())
    frames = _drain(session)
    kinds = [(f.channel, f.type) for f in frames]
    assert kinds[0] == (CHAT, "turn.start")
    assert kinds[-1] == (CHAT, "turn.end")
    tokens = [f.payload["text"] for f in frames if f.type == "token"]
    assert tokens == ["alpha", "beta", "gamma"]
    assert frames[-1].payload["text"] == "alphabetagamma"
    assert "cancelled" not in frames[-1].payload
    assert session.turn_status == "idle"


@pytest.mark.asyncio
async def test_reasoning_on_delivers_final_at_turn_end_no_tokens():
    session = _session()
    deps = _deps(_model(text="reasoned answer"), reasoning=True)
    await run_turn(session, deps, "hard question", CancelToken())
    frames = _drain(session)
    assert not [f for f in frames if f.type == "token"]
    end = frames[-1]
    assert end.type == "turn.end"
    assert end.payload["text"] == "reasoned answer"
    assert "confidence" in end.payload and "loops" in end.payload


@pytest.mark.asyncio
async def test_memory_retrieve_and_store_when_present():
    class FakeMemory:
        def __init__(self):
            self.retrieved = None
            self.stored = None

        async def retrieve(self, ctx, *, query, **kw):
            self.retrieved = query
            from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord
            return [MemoryRecord(id="1", trail_id=ctx.run_id, layer=MemoryLayer.EPISODIC,
                                 content=MemoryContent(text="past fact"),
                                 created_at=0.0, last_accessed=0.0)]

        def store(self, ctx, *, text, **kw):
            self.stored = text

    mem = FakeMemory()
    session = _session()
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hello", CancelToken())
    assert mem.retrieved == "hello"
    assert mem.stored is not None and "hello" in mem.stored and "ok" in mem.stored


@pytest.mark.asyncio
async def test_memory_none_skips_both_branches():
    session = _session()
    await run_turn(session, _deps(_model(script=["ok"]), memory=None), "hello", CancelToken())
    frames = _drain(session)
    assert [(f.channel, f.type) for f in frames] == [(CHAT, "turn.start"), (CHAT, "token"), (CHAT, "turn.end")]


@pytest.mark.asyncio
async def test_memory_retrieve_failure_degrades_not_aborts():
    class BrokenMemory:
        async def retrieve(self, ctx, *, query, **kw):
            raise RuntimeError("index down")

        def store(self, ctx, *, text, **kw):
            self.stored = text

    session = _session()
    await run_turn(session, _deps(_model(script=["ok"]), memory=BrokenMemory()), "hi", CancelToken())
    frames = _drain(session)
    assert frames[-1].type == "turn.end"  # completed, not error
    assert not [f for f in frames if f.type == "error"]


@pytest.mark.asyncio
async def test_cancelled_before_generate_emits_cancelled_end_and_skips_store():
    class SpyMemory:
        def __init__(self):
            self.stored = None

        async def retrieve(self, ctx, *, query, **kw):
            return []

        def store(self, ctx, *, text, **kw):
            self.stored = text

    mem = SpyMemory()
    session = _session()
    token = CancelToken()
    token.trip()  # already cancelled
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hi", token)
    frames = _drain(session)
    assert frames[-1].type == "turn.end"
    assert frames[-1].payload.get("cancelled") is True
    assert mem.stored is None  # no store on abort


@pytest.mark.asyncio
async def test_generation_exception_emits_chat_error():
    session = _session()
    await run_turn(session, _deps(_model(script=[RuntimeError("boom")])), "hi", CancelToken())
    frames = _drain(session)
    assert frames[-1].channel == CHAT and frames[-1].type == "error"
    assert session.turn_status == "idle"
