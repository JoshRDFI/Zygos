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
    await run_turn(session, _deps(_model(script=["alpha beta gamma"])), "hi", CancelToken(), spoken_input=False)
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
    await run_turn(session, deps, "hard question", CancelToken(), spoken_input=False)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hello", CancelToken(), spoken_input=False)
    assert mem.retrieved == "hello"
    assert mem.stored is not None and "hello" in mem.stored and "ok" in mem.stored


@pytest.mark.asyncio
async def test_memory_none_skips_both_branches():
    session = _session()
    await run_turn(session, _deps(_model(script=["ok"]), memory=None), "hello", CancelToken(), spoken_input=False)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=BrokenMemory()), "hi", CancelToken(), spoken_input=False)
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
    await run_turn(session, _deps(_model(script=["ok"]), memory=mem), "hi", token, spoken_input=False)
    frames = _drain(session)
    assert frames[-1].type == "turn.end"
    assert frames[-1].payload.get("cancelled") is True
    assert mem.stored is None  # no store on abort


@pytest.mark.asyncio
async def test_generation_exception_emits_chat_error():
    session = _session()
    await run_turn(session, _deps(_model(script=[RuntimeError("boom")])), "hi", CancelToken(), spoken_input=False)
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
    await run_turn(_session(), _deps(model), "hi", CancelToken(), spoken_input=False)
    assert _system_texts(provider.requests[0]) == []


@pytest.mark.asyncio
async def test_spoken_turn_tells_model_input_is_a_transcript():
    model, provider = _recording_model(text="ok")
    await run_turn(_session(), _deps(model), "hi", CancelToken(), spoken_input=True)
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
    await run_turn(session, deps, "hi", CancelToken(), spoken_input=False)
    (system,) = _system_texts(provider.requests[0])
    assert "text-to-speech" in system
    assert no_speech == ["ok"]  # same gate drove the actual speech


@pytest.mark.asyncio
async def test_speaker_on_without_tts_engine_is_not_spoken_output():
    model, provider = _recording_model(text="ok")
    session = _session()
    session.speak = True  # toggle on, but no voice service wired
    await run_turn(session, _deps(model), "hi", CancelToken(), spoken_input=False)
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
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=True)
    systems = [m.content for m in captured["messages"] if m.role == "system"]
    assert len(systems) == 1 and "speech-to-text" in systems[0]


@pytest.mark.asyncio
async def test_reasoning_path_receives_modality_message():
    seen = {}

    class _CapturingReasoning:
        async def run(self, ctx, input):
            seen["input"] = input
            from zygos.reasoning.types import ReasoningResult
            return ReasoningResult(text="r", loops_used=1, final_confidence=1.0,
                                   halted_early=False, model="m")

    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=_CapturingReasoning,
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "turn-1")
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=True)
    (system,) = seen["input"].system
    assert "speech-to-text" in system


@pytest.mark.asyncio
async def test_reasoning_path_typed_turn_has_no_system():
    seen = {}

    class _CapturingReasoning:
        async def run(self, ctx, input):
            seen["input"] = input
            from zygos.reasoning.types import ReasoningResult
            return ReasoningResult(text="r", loops_used=1, final_confidence=1.0,
                                   halted_early=False, model="m")

    model, _ = _recording_model(text="ok")
    deps = TurnDeps(model_service=model, reasoning_factory=_CapturingReasoning,
                    reasoning_enabled=True, memory_service=None, new_id=lambda: "turn-1")
    await run_turn(_session(), deps, "hi", CancelToken(), spoken_input=False)
    assert seen["input"].system == ()


@pytest.mark.asyncio
async def test_run_turn_requires_an_explicit_modality():
    # RFC-0010 Risks: a new turn-starting path must not silently default to typed.
    model, _ = _recording_model(text="ok")
    with pytest.raises(TypeError):
        await run_turn(_session(), _deps(model), "hi", CancelToken())
