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
    await run_turn(session, _deps(_model(script=["alpha beta gamma"])), "hi", CancelToken(), spoken_input=False, think=None)
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
    await run_turn(session, deps, "hard question", CancelToken(), spoken_input=False, think=None)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hello", CancelToken(), spoken_input=False, think=None)
    assert mem.retrieved == "hello"
    assert mem.stored is not None and "hello" in mem.stored and "ok" in mem.stored


@pytest.mark.asyncio
async def test_memory_none_skips_both_branches():
    session = _session()
    await run_turn(session, _deps(_model(script=["ok"]), memory=None), "hello", CancelToken(), spoken_input=False, think=None)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=BrokenMemory()), "hi", CancelToken(), spoken_input=False, think=None)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hi", token, spoken_input=False, think=None)
    frames = _drain(session)
    assert frames[-1].type == "turn.end"
    assert frames[-1].payload.get("cancelled") is True
    assert mem.stored is None  # no store on abort


@pytest.mark.asyncio
async def test_generation_exception_emits_chat_error():
    session = _session()
    await run_turn(session, _deps(_model(script=[RuntimeError("boom")])), "hi", CancelToken(), spoken_input=False, think=None)
    frames = _drain(session)
    assert frames[-1].channel == CHAT and frames[-1].type == "error"
    assert session.turn_status == "idle"


# --- RFC-0010 §3a: per-turn interaction-modality context -------------------------

from zygos.api.modality import TurnModality  # noqa: E402


class _RecordingProvider(FakeProvider):
    """FakeProvider that keeps every request it is sent."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return await super().generate(request)

    async def stream(self, request):
        self.requests.append(request)
        async for chunk in super().stream(request):
            yield chunk


def _recording_model(**kw):
    provider = _RecordingProvider(**kw)
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    return DefaultModelService(router), provider


def _system_texts(request):
    return [m.content for m in request.messages if m.role == "system"]


class _SpeakingVoice:
    """Just enough VoiceService for run_turn's spoken-output gate."""

    tts_available = True


@pytest.fixture
def no_speech(monkeypatch):
    """Skip real TTS; record that run_turn tried to speak."""
    spoken = []

    async def fake_speak_reply(session, voice, ctx, text, turn_id):
        spoken.append(text)

    monkeypatch.setattr("zygos.api.turn.speak_reply", fake_speak_reply)
    return spoken


def test_build_messages_default_is_unchanged_by_modality_seam():
    assert build_messages(("fact",), "hi") == build_messages(("fact",), "hi", TurnModality())


def test_build_messages_orders_modality_before_memory():
    msgs = build_messages(("fact A",), "hello", TurnModality(spoken_input=True))
    assert [m.role for m in msgs] == ["system", "system", "user"]
    assert "speech-to-text" in msgs[0].content
    assert "fact A" in msgs[1].content


@pytest.mark.asyncio
async def test_typed_turn_sends_no_modality_message():
    model, provider = _recording_model(text="ok")
    await run_turn(_session(), _deps(model), "hi", CancelToken(), spoken_input=False, think=None)
    assert _system_texts(provider.requests[0]) == []


@pytest.mark.asyncio
async def test_spoken_turn_tells_model_input_is_a_transcript():
    model, provider = _recording_model(text="ok")
    await run_turn(_session(), _deps(model), "hi", CancelToken(), spoken_input=True, think=None)
    (system,) = _system_texts(provider.requests[0])
    assert "speech-to-text" in system
    assert "text-to-speech" not in system  # speaker is off


@pytest.mark.asyncio
async def test_speaker_on_tells_model_reply_is_read_aloud(no_speech):
    model, provider = _recording_model(text="ok")
    session = _session()
    session.speak = True
    deps = TurnDeps(model_service=model, reasoning_factory=lambda: None,
                    reasoning_enabled=False, memory_service=None,
                    new_id=lambda: "turn-1", voice_service=_SpeakingVoice())
    await run_turn(session, deps, "hi", CancelToken(), spoken_input=False, think=None)
    (system,) = _system_texts(provider.requests[0])
    assert "text-to-speech" in system
    assert no_speech == ["ok"]  # same gate drove the actual speech


@pytest.mark.asyncio
async def test_speaker_on_without_tts_engine_is_not_spoken_output():
    model, provider = _recording_model(text="ok")
    session = _session()
    session.speak = True  # toggle on, but no voice service wired
    await run_turn(session, _deps(model), "hi", CancelToken(), spoken_input=False, think=None)
    assert _system_texts(provider.requests[0]) == []


@pytest.mark.asyncio
async def test_tools_path_receives_modality_message(monkeypatch):
    captured = {}

    async def fake_loop(ctx, *, messages, **kw):
        captured["messages"] = messages

        class _R:
            text, stop_reason, iterations = "done", "final", 1
        return _R()

    monkeypatch.setattr("zygos.api.turn.run_agentic_loop", fake_loop)
    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=lambda: None,
                    reasoning_enabled=False, memory_service=None,
                    new_id=lambda: "turn-1", tools=(object(),))
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=True, think=None)
    systems = [m.content for m in captured["messages"] if m.role == "system"]
    assert len(systems) == 1 and "speech-to-text" in systems[0]


@pytest.mark.asyncio
async def test_reasoning_path_receives_modality_message():
    seen = {}

    class _CapturingReasoning:
        async def run(self, ctx, input, thinking=None):
            seen["input"] = input
            from zygos.reasoning.types import ReasoningResult
            return ReasoningResult(text="r", loops_used=1, final_confidence=1.0,
                                   halted_early=False, model="m")

    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=_CapturingReasoning,
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "turn-1")
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=True, think=None)
    (system,) = seen["input"].system
    assert "speech-to-text" in system


@pytest.mark.asyncio
async def test_reasoning_path_typed_turn_has_no_system():
    seen = {}

    class _CapturingReasoning:
        async def run(self, ctx, input, thinking=None):
            seen["input"] = input
            from zygos.reasoning.types import ReasoningResult
            return ReasoningResult(text="r", loops_used=1, final_confidence=1.0,
                                   halted_early=False, model="m")

    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=_CapturingReasoning,
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "turn-1")
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    assert seen["input"].system == ()


@pytest.mark.asyncio
async def test_run_turn_requires_an_explicit_modality():
    # RFC-0010 Risks: a new turn-starting path must not silently default to typed.
    model, _ = _recording_model(text="ok")
    with pytest.raises(TypeError):
        await run_turn(_session(), _deps(model), "hi", CancelToken())


# --- RFC-0010 §3 identity injection ---------------------------------------
import logging  # noqa: E402
import sqlite3  # noqa: E402

from zygos.personalization import Personalization  # noqa: E402


class _DictStore:
    def __init__(self, prefs=None):
        self.prefs = prefs or Personalization()

    def get(self):
        return self.prefs

    def set(self, prefs):
        self.prefs = prefs


def _prefs_deps(model, store, **kw):
    return TurnDeps(model_service=model, reasoning_factory=lambda: None,
                    reasoning_enabled=False, memory_service=None,
                    new_id=lambda: "turn-1", preferences=store, **kw)


def test_build_messages_empty_prefs_is_byte_identical():
    assert build_messages(("m",), "hi") == build_messages(
        ("m",), "hi", TurnModality(), Personalization())


def test_build_messages_orders_identity_modality_memory():
    msgs = build_messages(("fact",), "hi", TurnModality(spoken_input=True),
                          Personalization(user_name="Josh"))
    assert [m.role for m in msgs] == ["system", "system", "system", "user"]
    assert "Josh" in msgs[0].content
    assert "speech-to-text" in msgs[1].content
    assert "fact" in msgs[2].content


@pytest.mark.asyncio
async def test_turn_reads_store_each_turn():
    model, provider = _recording_model(text="ok")
    store = _DictStore()
    deps = _prefs_deps(model, store)
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    assert _system_texts(provider.requests[0]) == []
    store.set(Personalization(user_name="Josh"))
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    (system,) = _system_texts(provider.requests[1])
    assert "Josh" in system


@pytest.mark.asyncio
async def test_broken_store_degrades_turn(caplog):
    class _Broken:
        def get(self):
            raise sqlite3.OperationalError("locked")

    model, provider = _recording_model(text="ok")
    session = _session()
    with caplog.at_level(logging.WARNING, logger="zygos.api.turn"):
        await run_turn(session, _prefs_deps(model, _Broken()), "hi", CancelToken(),
                       spoken_input=False, think=None)
    assert _system_texts(provider.requests[0]) == []
    assert any(f.type == "turn.end" for f in _drain(session))
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.asyncio
async def test_reasoning_path_receives_identity():
    seen = {}

    class _CapturingReasoning:
        async def run(self, ctx, input, thinking=None):
            seen["input"] = input
            from zygos.reasoning.types import ReasoningResult
            return ReasoningResult(text="r", loops_used=1, final_confidence=1.0,
                                   halted_early=False, model="m")

    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=_CapturingReasoning,
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "turn-1",
                    preferences=_DictStore(Personalization(assistant_name="Rommie")))
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    assert "Rommie" in seen["input"].system[0]


@pytest.mark.asyncio
async def test_tools_path_receives_identity(monkeypatch):
    captured = {}

    async def fake_loop(ctx, *, messages, **kw):
        captured["messages"] = messages

        class _R:
            text, stop_reason, iterations = "done", "final", 1
        return _R()

    monkeypatch.setattr("zygos.api.turn.run_agentic_loop", fake_loop)
    model, _ = _recording_model(text="ok")
    deps = _prefs_deps(model, _DictStore(Personalization(assistant_name="Rommie")),
                       tools=(object(),))
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    systems = [m.content for m in captured["messages"] if m.role == "system"]
    assert "Rommie" in systems[0]


# --- RFC-0012: per-turn native thinking ------------------------------------
import asyncio  # noqa: E402

from pydantic import BaseModel, ConfigDict, Field  # noqa: E402

from zygos.tools.types import BaseTool, ToolMeta  # noqa: E402

from zygos.agent.config import ToolLoopConfig  # noqa: E402
from zygos.providers.types import GenerationChunk  # noqa: E402
from zygos.thinking.support import ThinkingSupportChecker  # noqa: E402
from zygos.tools.service import ToolService  # noqa: E402
from zygos.voice.types import AudioFormat  # noqa: E402


def _think_deps(model, **kw):
    kw.setdefault("think_default", False)
    return TurnDeps(model_service=model,
                    reasoning_factory=lambda: DefaultReasoningService(
                        model, ReasoningConfig(enabled=True, profile="shallow")),
                    reasoning_enabled=kw.pop("reasoning", False), memory_service=kw.pop("memory", None),
                    new_id=kw.pop("new_id", lambda: "turn-1"), **kw)


def _start(frames):
    return next(f for f in frames if f.type == "turn.start")


def _end(frames):
    return next(f for f in frames if f.type == "turn.end")


async def test_run_turn_requires_an_explicit_think():
    model, _ = _recording_model(text="ok")
    with pytest.raises(TypeError):
        await run_turn(_session(), _deps(model), "hi", CancelToken(), spoken_input=False)


async def test_default_turn_unchanged():
    model, provider = _recording_model(text="ok")
    session = _session()
    await run_turn(session, _think_deps(model), "hi", CancelToken(), spoken_input=False, think=None)
    assert provider.requests[0].think is False
    frames = _drain(session)
    assert _start(frames).payload == {"turn_id": "turn-1", "think": False, "rethink_of": None}
    end = _end(frames).payload
    assert end["think"] is False
    assert end["thinking_ms"] is None
    assert end["think_unsupported_reason"] is None


class _EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(description="value")


class _EchoTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(name="echo", description="Echo.", input_model=_EchoInput,
                             permission="allow")

    async def execute(self, input, ctx):
        return {"echoed": input.value}


def _path_kwargs(path):
    if path == "tools":
        ts = ToolService()
        tool = _EchoTool()
        ts.register(tool)
        return {"tool_service": ts, "tools": (tool,), "tool_loop_config": ToolLoopConfig()}
    if path == "reasoning":
        return {"reasoning": True}
    return {}


@pytest.mark.parametrize("path", ["direct", "tools", "reasoning"])
async def test_explicit_think_reaches_each_path(path):
    model, provider = _recording_model(text="ok")
    deps = _think_deps(model, **_path_kwargs(path))
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=True)
    assert provider.requests and all(r.think is True for r in provider.requests)
    n = len(provider.requests)
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False, think=None)
    assert provider.requests[n:] and all(r.think is False for r in provider.requests[n:])


async def test_null_config_reports_null():
    model, provider = _recording_model(text="ok")
    session = _session()
    await run_turn(session, _think_deps(model, think_default=None), "hi", CancelToken(),
                   spoken_input=False, think=None)
    assert provider.requests[0].think is None
    frames = _drain(session)
    assert _start(frames).payload["think"] is None
    assert _end(frames).payload["think"] is None


class _ThinkingStreamProvider(_RecordingProvider):
    async def stream(self, request):
        self.requests.append(request)
        yield GenerationChunk(text="", thinking="a")
        yield GenerationChunk(text="", thinking="b")
        yield GenerationChunk(text="final")
        yield GenerationChunk(text="", done=True)


def _thinking_model():
    provider = _ThinkingStreamProvider()
    return DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))


async def test_direct_path_records_thinking():
    bus = InProcessEventBus()
    events = []

    async def on_event(e):
        if e.type == "model.thinking":
            events.append(e.payload)

    bus.subscribe(on_event)
    session = _session(bus)
    await run_turn(session, _think_deps(_thinking_model()), "hi", CancelToken(),
                   spoken_input=False, think=True)
    assert len(events) == 1
    ev = events[0]
    assert (ev.step, ev.index, ev.text, ev.turn_id) == ("direct", 0, "ab", "turn-1")
    frames = _drain(session)
    end = _end(frames).payload
    assert isinstance(end["thinking_ms"], int) and end["thinking_ms"] >= 0
    assert end["text"] == "final"
    for f in frames:
        assert "ab" not in str(f.payload.get("text", ""))


async def test_thinking_absent_from_memory():
    class SpyMemory:
        stored = None

        async def retrieve(self, ctx, *, query, **kw):
            return []

        def store(self, ctx, *, text, **kw):
            self.stored = text

    mem = SpyMemory()
    await run_turn(_session(), _think_deps(_thinking_model(), memory=mem), "hi", CancelToken(),
                   spoken_input=False, think=True)
    assert mem.stored == format_exchange("hi", "final")


async def test_unsupported_reason_on_turn_end():
    model, provider = _recording_model(text="ok")
    checker = ThinkingSupportChecker({"fake": FakeProvider(think_capable=False)})
    session = _session()
    await run_turn(session, _think_deps(model, thinking_support=checker), "hi", CancelToken(),
                   spoken_input=False, think=True)
    assert provider.requests[0].think is False
    frames = _drain(session)
    assert _start(frames).payload["think"] is False
    end = _end(frames).payload
    assert end["think"] is False
    assert end["think_unsupported_reason"] == "m can't think"


async def test_cancelled_turn_end_carries_think_fields():
    model, _ = _recording_model(text="ok")
    session = _session()
    token = CancelToken()
    token.trip()
    await run_turn(session, _think_deps(model), "hi", token, spoken_input=False, think=True)
    end = _end(_drain(session)).payload
    assert end["cancelled"] is True
    assert end["think"] is True
    assert "thinking_ms" in end and end["think_unsupported_reason"] is None


async def test_rethink_of_echoed():
    model, _ = _recording_model(text="ok")
    session = _session()
    await run_turn(session, _think_deps(model), "hi", CancelToken(), spoken_input=False,
                   think=True, rethink_of="t1")
    assert _start(_drain(session)).payload["rethink_of"] == "t1"


async def test_last_user_text_and_turn_id_set():
    model, _ = _recording_model(text="ok")
    session = _session()
    assert session.think is None and session.last_user_text is None and session.last_turn_id is None
    await run_turn(session, _think_deps(model), "what now", CancelToken(), spoken_input=False,
                   think=None)
    assert session.last_user_text == "what now"
    assert session.last_turn_id == "turn-1"


class _Synth:
    def __init__(self, gate=None, started=None):
        self._gate = gate
        self._started = started

    async def chunks(self):
        if self._started is not None:
            self._started.set()
        if self._gate is not None:
            await self._gate.wait()
        yield b"\x00\x00"

    async def cancel(self):
        pass

    async def aclose(self):
        pass


class _RecordingVoice:
    tts_available = True

    def __init__(self, block_text=None):
        self.texts = []
        self.block_text = block_text
        self.gate = asyncio.Event()
        self.started = asyncio.Event()

    @property
    def tts_format(self):
        return AudioFormat(sample_rate=24000)

    def synthesize_stream(self, ctx, text):
        self.texts.append(text)
        if text == self.block_text:
            return _Synth(self.gate, self.started)
        return _Synth()


async def test_spoken_thinking_turn_speaks_prefix_first():
    model, _ = _recording_model(text="the answer")
    voice = _RecordingVoice()
    session = _session()
    session.speak = True
    deps = _think_deps(model, voice_service=voice)
    await run_turn(session, deps, "hi", CancelToken(), spoken_input=True, think=True)
    assert voice.texts == ["Let me think about that.", "theanswer"]

    for spoken, think in [(True, False), (True, None), (False, True)]:
        voice.texts.clear()
        await run_turn(session, deps, "hi", CancelToken(), spoken_input=spoken, think=think)
        assert "Let me think about that." not in voice.texts


class _GatedStreamProvider(_RecordingProvider):
    def __init__(self, release, **kw):
        super().__init__(**kw)
        self.release = release

    async def stream(self, request):
        self.requests.append(request)
        await self.release.wait()
        yield GenerationChunk(text="late")
        yield GenerationChunk(text="", done=True)


async def test_cancel_during_prefix_leaves_no_task(monkeypatch):
    import zygos.api.turn as turn_mod

    created = []
    real_create_task = asyncio.create_task

    def spy_create_task(coro, **kw):
        task = real_create_task(coro, **kw)
        created.append(task)
        return task

    monkeypatch.setattr(turn_mod.asyncio, "create_task", spy_create_task)
    release = asyncio.Event()
    provider = _GatedStreamProvider(release)
    model = DefaultModelService(ProviderRouter([RouteChoice("fake", "m")], {"fake": provider}))
    voice = _RecordingVoice(block_text="Let me think about that.")
    session = _session()
    session.speak = True
    token = CancelToken()
    turn = real_create_task(run_turn(session, _think_deps(model, voice_service=voice), "hi", token,
                                     spoken_input=True, think=True))
    await asyncio.wait_for(voice.started.wait(), 1.0)  # prefix is synthesizing
    token.trip()
    release.set()
    await asyncio.wait_for(turn, 1.0)
    end = _end(_drain(session)).payload
    assert end["cancelled"] is True
    assert end["think"] is True and "thinking_ms" in end and "think_unsupported_reason" in end
    assert voice.texts == ["Let me think about that."]  # final reply never synthesized
    assert created and all(t.done() for t in created)
