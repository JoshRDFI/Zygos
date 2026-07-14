import json

import pytest
from pydantic import BaseModel, ConfigDict, Field

from zygos.agent.config import ToolLoopConfig
from zygos.api.frames import CHAT, TOOLS
from zygos.api.session import Session
from zygos.api.turn import TurnDeps, run_turn
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationResult, ToolInvocation
from zygos.reasoning.service import DefaultReasoningService
from zygos.config.schema import ReasoningConfig
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice
from zygos.tools.service import ToolService
from zygos.tools.types import BaseTool, ToolContext, ToolMeta


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(description="value")


class EchoTool(BaseTool):
    def __init__(self):
        self.meta = ToolMeta(name="echo", description="Echo.", input_model=EchoInput, permission="allow")

    async def execute(self, input: EchoInput, ctx: ToolContext) -> dict:
        return {"echoed": input.value}


def _session():
    return Session("s1", root_context(InProcessEventBus(), session_id="s1"), created_at=0.0)


def _model(script):
    provider = FakeProvider(script=script)
    router = ProviderRouter([RouteChoice("fake", "m")], {"fake": provider})
    return DefaultModelService(router)


def _call(name, args, cid="c1"):
    return GenerationResult(text="", model="m", provider="fake",
                            tool_calls=(ToolInvocation(id=cid, name=name, arguments=args),),
                            finish_reason="tool_calls")


def _tool_service():
    ts = ToolService()
    ts.register(EchoTool())
    return ts


def _deps(model, *, tools=(EchoTool(),), reasoning=False):
    return TurnDeps(
        model_service=model,
        reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True, profile="shallow")),
        reasoning_enabled=reasoning,
        memory_service=None,
        new_id=lambda: "turn-1",
        tool_service=_tool_service(),
        tools=tuple(tools),
        tool_loop_config=ToolLoopConfig(),
    )


def _drain(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


@pytest.mark.asyncio
async def test_tools_turn_emits_call_result_then_turn_end():
    session = _session()
    model = _model([_call("echo", {"value": "hi"}), "the echo was hi"])
    await run_turn(session, _deps(model), "echo hi", CancelToken())
    kinds = [(f.channel, f.type) for f in _drain(session)]
    assert kinds[0] == (CHAT, "turn.start")
    assert (TOOLS, "call") in kinds
    assert (TOOLS, "result") in kinds
    assert kinds[-1] == (CHAT, "turn.end")


@pytest.mark.asyncio
async def test_tools_turn_result_payload_and_final_text():
    session = _session()
    model = _model([_call("echo", {"value": "hi"}), "final answer"])
    await run_turn(session, _deps(model), "echo hi", CancelToken())
    frames = _drain(session)
    result = next(f for f in frames if f.type == "result")
    assert result.payload["ok"] is True
    assert result.payload["output"] == {"echoed": "hi"}
    end = frames[-1]
    assert end.payload["text"] == "final answer"
    assert end.payload["stop_reason"] == "stop"


@pytest.mark.asyncio
async def test_tools_present_overrides_reasoning_enabled():
    session = _session()
    model = _model(["no tools here"])   # model returns plain text on first call
    await run_turn(session, _deps(model, reasoning=True), "hi", CancelToken())
    frames = _drain(session)
    # went through the agentic loop (no chat:token frames), ended with the loop's answer
    assert not any(f.type == "token" for f in frames)
    assert frames[-1].payload["text"] == "no tools here"


@pytest.mark.asyncio
async def test_no_tools_falls_through_to_streaming():
    session = _session()
    model = _model(["alpha beta"])
    deps = _deps(model, tools=())
    await run_turn(session, deps, "hi", CancelToken())
    frames = _drain(session)
    assert [f.payload["text"] for f in frames if f.type == "token"] == ["alpha", "beta"]


@pytest.mark.asyncio
async def test_cancelled_before_start_ends_cancelled():
    session = _session()
    model = _model(["unused"])
    token = CancelToken()
    token.trip()
    await run_turn(session, _deps(model), "hi", token)
    frames = _drain(session)
    assert frames[-1].payload.get("cancelled") is True
