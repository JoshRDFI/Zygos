"""RFC-0013 §5, §10, §11: turns report the answering model and category; loading frame.

The route is pinned once per turn (controller ruling P5): a default change made
while a turn runs does not affect it.
"""

from contextlib import asynccontextmanager

import pytest

from zygos.agent.config import ToolLoopConfig
from zygos.api.frames import CHAT
from zygos.api.session import Session
from zygos.api.turn import TurnDeps, run_turn
from zygos.config.schema import ReasoningConfig
from zygos.errors import ProviderUnavailable
from zygos.models.default import DefaultModel, DefaultStatus
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationResult, ToolInvocation
from zygos.reasoning.service import DefaultReasoningService
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import CATEGORY_OF, DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice
from zygos.tools.service import ToolService
from tests.api.test_turn_tools import EchoTool

PRIMARY = RouteChoice("fake", "m")
SAVED = RouteChoice("other", "s")
LATER = RouteChoice("third", "t")


class _Recording(FakeProvider):
    """A FakeProvider that records every request it is asked for."""

    def __init__(self, name, **kw):
        super().__init__(**kw)
        self.name = name
        self.calls = 0

    async def generate(self, request):
        self.calls += 1
        return await super().generate(request)

    async def stream(self, request):
        self.calls += 1
        async for chunk in super().stream(request):
            yield chunk


class _Rig:
    def __init__(self, *, saved=SAVED, primary_script=None, saved_script=None,
                 ignored_reason=None, residency=None, saved_provider=None):
        self.primary = _Recording("fake", script=primary_script, text="primary answer")
        self.saved = saved_provider or _Recording("other", script=saved_script, text="saved answer")
        self.third = _Recording("third", text="later answer")
        providers = {"fake": self.primary, "other": self.saved, "third": self.third}
        if saved is not None and saved.provider not in providers:
            providers[saved.provider] = self.saved
        self.router = ProviderRouter([PRIMARY], providers, max_attempts=1)
        if saved is None:
            self.status = DefaultStatus(source="config", route=PRIMARY)
        elif ignored_reason is not None:
            self.status = DefaultStatus(source="config", route=PRIMARY,
                                        ignored=DefaultModel(provider=saved.provider, model=saved.model),
                                        reason=ignored_reason)
        else:
            self.status = DefaultStatus(source="saved", route=saved)
        self.service = DefaultModelService(self.router, default_status=lambda: self.status,
                                           residency=residency)
        self.bus = InProcessEventBus()
        self.events = []

        async def _record(event):
            self.events.append(event)
        self.bus.subscribe(_record)
        self.session = Session("s1", root_context(self.bus, session_id="s1"), created_at=0.0)

    def change_default(self, route):
        self.status = DefaultStatus(source="saved", route=route)

    def deps(self, *, reasoning=False, tools=False, default_status=True):
        model = self.service
        return TurnDeps(
            model_service=model,
            reasoning_factory=lambda: DefaultReasoningService(
                model, ReasoningConfig(enabled=True, profile="shallow")),
            reasoning_enabled=reasoning,
            memory_service=None,
            new_id=lambda: "turn-1",
            tool_service=_tools() if tools else None,
            tools=(EchoTool(),) if tools else (),
            tool_loop_config=ToolLoopConfig() if tools else None,
            default_status=(lambda: self.status) if default_status else None,
        )

    def frames(self):
        out = []
        while not self.session.outbound.empty():
            out.append(self.session.outbound.get_nowait())
        return out

    def of_type(self, type_):
        return [e.payload for e in self.events if e.type == type_]


def _tools():
    ts = ToolService()
    ts.register(EchoTool())
    return ts


def _call(name, args, cid="c1"):
    return GenerationResult(text="", model="s", provider="other",
                            tool_calls=(ToolInvocation(id=cid, name=name, arguments=args),),
                            finish_reason="tool_calls")


async def _turn(rig, text="hi", **deps_kw):
    await run_turn(rig.session, rig.deps(**deps_kw), text, CancelToken(),
                   spoken_input=False, think=None)
    return rig.frames()


def _end(frames):
    (end,) = [f for f in frames if f.channel == CHAT and f.type == "turn.end"]
    return end.payload


def test_category_of_is_exact():
    assert CATEGORY_OF == {"code": "code", "complex_reasoning": "reasoning",
                           "simple": "chat", "standard": "chat"}


# --- direct stream path -------------------------------------------------------

@pytest.mark.asyncio
async def test_direct_turn_reports_saved_default_and_category():
    rig = _Rig()
    end = _end(await _turn(rig, "hi"))
    assert end["model"] == {"provider": "other", "model": "s"}
    assert end["category"] == "chat"
    assert end["text"] == "savedanswer"


@pytest.mark.asyncio
async def test_direct_turn_category_from_text():
    rig = _Rig()
    assert _end(await _turn(rig, "def foo(): pass"))["category"] == "code"
    rig2 = _Rig()
    assert _end(await _turn(rig2, "why is the sky blue"))["category"] == "reasoning"


@pytest.mark.asyncio
async def test_saved_default_failing_reports_config_primary():
    rig = _Rig(saved_script=[ProviderUnavailable("down", provider="other")])
    end = _end(await _turn(rig, "hi"))
    assert end["model"] == {"provider": "fake", "model": "m"}
    assert end["text"] == "primaryanswer"


@pytest.mark.asyncio
async def test_no_saved_default_only_adds_model_and_category():
    rig = _Rig(saved=None)
    end = _end(await _turn(rig, "hi"))
    assert end["model"] == {"provider": "fake", "model": "m"}
    assert end["category"] == "chat"
    assert set(end) == {"text", "model", "category", "think", "thinking_ms",
                        "think_unsupported_reason", "rethink_of"}
    assert rig.saved.calls == 0


@pytest.mark.asyncio
async def test_direct_turn_pins_route_when_default_changes_mid_stream():
    rig = None

    class _Flipping(_Recording):
        async def stream(self, request):
            rig.change_default(LATER)
            async for chunk in super().stream(request):
                yield chunk

    rig = _Rig(saved_provider=_Flipping("other", text="saved answer"))
    end = _end(await _turn(rig, "hi"))
    assert end["model"] == {"provider": "other", "model": "s"}
    assert rig.third.calls == 0


# --- loading frame ------------------------------------------------------------

class _LoadingResidency:
    def __init__(self):
        self.loaded = []

    async def ensure_resident(self, ctx, route, *, on_loading=None):
        if on_loading is not None:
            on_loading(route)
        self.loaded.append(route)

    @asynccontextmanager
    async def turn(self, route):
        yield


@pytest.mark.asyncio
async def test_loading_frame_before_first_token():
    local = RouteChoice("fake", "big")
    rig = _Rig(saved=local, residency=_LoadingResidency())
    frames = await _turn(rig, "hi")
    kinds = [(f.channel, f.type) for f in frames]
    loading_at = kinds.index((CHAT, "model.loading"))
    first_token = kinds.index((CHAT, "token"))
    assert loading_at < first_token
    assert frames[loading_at].payload == {"turn_id": "turn-1", "provider": "fake", "model": "big"}
    assert _end(frames)["model"] == {"provider": "fake", "model": "big"}


@pytest.mark.asyncio
async def test_no_loading_frame_without_a_load():
    rig = _Rig()
    frames = await _turn(rig, "hi")
    assert not [f for f in frames if f.type == "model.loading"]


# --- agentic (tools) path -----------------------------------------------------

@pytest.mark.asyncio
async def test_tools_turn_reports_saved_default():
    rig = _Rig(saved_script=[_call("echo", {"value": "hi"}), "final answer"])
    end = _end(await _turn(rig, "echo hi", tools=True))
    assert end["model"] == {"provider": "other", "model": "s"}
    assert end["category"] == "chat"
    assert end["text"] == "final answer"


@pytest.mark.asyncio
async def test_tools_turn_default_changed_between_generates_keeps_original_route():
    rig = None

    class _FlippingOther(_Recording):
        async def generate(self, request):
            result = await super().generate(request)
            rig.change_default(LATER)  # the user picks another model mid-turn
            return result

    rig = _Rig(saved_provider=_FlippingOther(
        "other", script=[_call("echo", {"value": "hi"}), "final answer"]))
    end = _end(await _turn(rig, "echo hi", tools=True))
    assert rig.saved.calls == 2          # both generate calls went to the pinned route
    assert rig.third.calls == 0
    assert end["model"] == {"provider": "other", "model": "s"}
    # the next turn picks up the change
    rig.third._script = None
    end2 = _end(await _turn(rig, "hi", tools=True))
    assert end2["model"] == {"provider": "third", "model": "t"}


# --- reasoning path -----------------------------------------------------------

@pytest.mark.asyncio
async def test_reasoning_turn_reports_saved_default_and_selected_matches():
    rig = _Rig()
    end = _end(await _turn(rig, "hard question", reasoning=True))
    assert end["model"] == {"provider": "other", "model": "s"}
    assert end["category"] == "chat"
    (selected,) = rig.of_type("model.selected")
    assert (selected.provider, selected.model) == ("other", "s")
    assert rig.primary.calls == 0


@pytest.mark.asyncio
async def test_reasoning_turn_default_changed_mid_run_keeps_original_route():
    rig = None

    class _FlippingOther(_Recording):
        async def generate(self, request):
            rig.change_default(LATER)
            return await super().generate(request)

    rig = _Rig(saved_provider=_FlippingOther("other", text="saved answer"))
    end = _end(await _turn(rig, "hard question", reasoning=True))
    assert rig.saved.calls >= 2
    assert rig.third.calls == 0
    assert end["model"] == {"provider": "other", "model": "s"}


@pytest.mark.asyncio
async def test_reasoning_turn_without_saved_default_reports_primary():
    rig = _Rig(saved=None)
    end = _end(await _turn(rig, "hard question", reasoning=True))
    assert end["model"] == {"provider": "fake", "model": "m"}
    (selected,) = rig.of_type("model.selected")
    assert (selected.provider, selected.model) == ("fake", "m")


# --- model.chosen trace -------------------------------------------------------

@pytest.mark.asyncio
async def test_model_chosen_saved_default_emitted_before_generation():
    rig = _Rig()
    await _turn(rig, "hi")
    types = [e.type for e in rig.events]
    assert types.count("model.chosen") == 1
    assert types.index("model.chosen") < types.index("route.claimed")
    (event,) = [e for e in rig.events if e.type == "model.chosen"]
    assert event.session_id == "s1"
    assert event.payload.model_dump() == {
        "type": "model.chosen", "turn_id": "turn-1", "category": "chat",
        "provider": "other", "model": "s", "mode": "default", "reason": "saved default"}


@pytest.mark.asyncio
async def test_model_chosen_config_default():
    rig = _Rig(saved=None)
    await _turn(rig, "hi")
    (chosen,) = rig.of_type("model.chosen")
    assert (chosen.provider, chosen.model, chosen.reason) == ("fake", "m", "config default")


@pytest.mark.asyncio
async def test_model_chosen_saved_default_ignored():
    rig = _Rig(ignored_reason="other isn't available")
    end = _end(await _turn(rig, "hi"))
    (chosen,) = rig.of_type("model.chosen")
    assert (chosen.provider, chosen.model) == ("fake", "m")
    assert chosen.reason == "saved default ignored: other isn't available"
    assert end["model"] == {"provider": "fake", "model": "m"}


@pytest.mark.asyncio
async def test_model_chosen_without_default_status_dep_is_config_default():
    rig = _Rig(saved=None)
    await _turn(rig, "hi", default_status=False)
    (chosen,) = rig.of_type("model.chosen")
    assert chosen.reason == "config default"


# --- cancelled / failed -------------------------------------------------------

@pytest.mark.asyncio
async def test_cancelled_before_generation_has_null_model_and_category():
    rig = _Rig()
    cancel = CancelToken()
    cancel.trip()
    await run_turn(rig.session, rig.deps(), "hi", cancel, spoken_input=False, think=None)
    end = _end(rig.frames())
    assert end["cancelled"] is True
    assert end["model"] is None
    assert end["category"] == "chat"


@pytest.mark.asyncio
async def test_failed_turn_sends_error_and_no_turn_end():
    rig = _Rig(saved=None, primary_script=[ProviderUnavailable("down", provider="fake")])
    frames = await _turn(rig, "hi")
    assert [f.type for f in frames if f.channel == CHAT][-1] == "error"
    assert not [f for f in frames if f.type == "turn.end"]


def test_app_turn_deps_carry_runtime_default_status():
    from zygos.api.app import create_app
    from zygos.runtime.bootstrap import build_runtime
    runtime = build_runtime()
    assert create_app(runtime).state.turn_deps.default_status is runtime.default_status
