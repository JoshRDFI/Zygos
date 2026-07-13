import json

from pydantic import BaseModel, ConfigDict, Field

from zygos.agent.config import ToolLoopConfig
from zygos.agent.loop import AgentResult, run_agentic_loop
from zygos.providers.fake import FakeProvider
from zygos.providers.types import GenerationResult, Message, ToolInvocation
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.services.model import DefaultModelService
from zygos.services.router import ProviderRouter, RouteChoice
from zygos.tools.service import ToolService
from zygos.tools.types import BaseTool, ToolContext, ToolMeta


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str = Field(description="the value to echo")


class EchoTool(BaseTool):
    def __init__(self) -> None:
        self.meta = ToolMeta(name="echo", description="Echo the value.", input_model=EchoInput,
                             permission="allow")

    async def execute(self, input: EchoInput, ctx: ToolContext) -> dict:
        return {"echoed": input.value}


class BoomTool(BaseTool):
    def __init__(self) -> None:
        self.meta = ToolMeta(name="boom", description="Always fails.", input_model=EchoInput,
                             permission="allow")

    async def execute(self, input: EchoInput, ctx: ToolContext) -> dict:
        from zygos.errors import ToolError
        raise ToolError("kaboom")


def _model_service(script) -> DefaultModelService:
    fake = FakeProvider(script=script)
    router = ProviderRouter(routes=[RouteChoice("fake", "fake-model")], providers={"fake": fake})
    return DefaultModelService(router)


def _tool_service(*tools) -> ToolService:
    svc = ToolService()   # default policy = all-allow
    for t in tools:
        svc.register(t)
    return svc


def _ctx():
    return root_context(InProcessEventBus())


def _call(name, args, cid="c1"):
    return GenerationResult(text="", model="fake-model", provider="fake",
                            tool_calls=(ToolInvocation(id=cid, name=name, arguments=args),),
                            finish_reason="tool_calls")


async def test_single_tool_call_then_answer():
    ms = _model_service([_call("echo", {"value": "hi"}), "the echo was hi"])
    ts = _tool_service(EchoTool())
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="echo hi")], config=ToolLoopConfig())
    assert isinstance(result, AgentResult)
    assert result.text == "the echo was hi"
    assert result.stop_reason == "stop"
    # history: user, assistant(tool_calls), tool(result)
    roles = [m.role for m in result.messages]
    assert roles == ["user", "assistant", "tool"]
    assert json.loads(result.messages[2].content) == {"echoed": "hi"}
    assert result.messages[2].tool_call_id == "c1"


async def test_tool_failure_rendered_as_structured_error():
    ms = _model_service([_call("boom", {"value": "x"}), "it failed"])
    ts = _tool_service(BoomTool())
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[BoomTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig())
    payload = json.loads(result.messages[2].content)
    assert set(payload) == {"error", "message"}
    assert payload["error"]  # a non-empty error code
    assert result.text == "it failed"


async def test_hallucinated_tool_name_fed_back_as_error():
    ms = _model_service([_call("nonexistent", {"value": "x"}), "sorry, no such tool"])
    ts = _tool_service(EchoTool())   # 'nonexistent' is NOT registered
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig())
    payload = json.loads(result.messages[2].content)
    assert payload["error"] == "tool_not_found"
    assert result.text == "sorry, no such tool"
    assert result.stop_reason == "stop"


async def test_no_tool_calls_returns_immediately():
    ms = _model_service(["just text"])
    ts = _tool_service(EchoTool())
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="hi")], config=ToolLoopConfig())
    assert result.text == "just text"
    assert result.iterations == 1
    assert [m.role for m in result.messages] == ["user"]


async def test_multiple_tool_calls_execute_and_history_ordered():
    two_calls = GenerationResult(
        text="", model="fake-model", provider="fake", finish_reason="tool_calls",
        tool_calls=(ToolInvocation(id="a", name="echo", arguments={"value": "1"}),
                    ToolInvocation(id="b", name="echo", arguments={"value": "2"})))
    ms = _model_service([two_calls, "done"])
    ts = _tool_service(EchoTool())
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig())
    # user, assistant(2 calls), tool(a), tool(b), then final answer returned as text
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["a", "b"]
    assert json.loads(tool_msgs[0].content) == {"echoed": "1"}
    assert json.loads(tool_msgs[1].content) == {"echoed": "2"}
    assert result.text == "done"


async def test_cancelled_context_returns_before_generate():
    ms = _model_service(["should not be used"])
    ts = _tool_service(EchoTool())
    ctx = _ctx()
    ctx._cancel.trip()   # pre-cancel
    result = await run_agentic_loop(
        ctx, model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig())
    assert result.stop_reason == "cancelled"
    assert result.iterations == 0


async def test_max_iterations_triggers_final_tool_choice_none():
    # A model that always requests a tool -> loop must cap and force a tool-free answer.
    calls = [_call("echo", {"value": "x"}, cid=f"c{i}") for i in range(3)]
    # After 2 rounds, the 3rd generate is the forced final (tool_choice="none") -> text.
    ms = _model_service(calls[:2] + ["forced final answer"])
    ts = _tool_service(EchoTool())
    result = await run_agentic_loop(
        _ctx(), model_service=ms, tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig(max_iterations=2))
    assert result.stop_reason == "max_iterations"
    assert result.iterations == 2
    assert result.text == "forced final answer"


async def test_final_generate_uses_tool_choice_none():
    # Assert the forced-final request carries tool_choice="none" by capturing it.
    seen: list[str] = []

    class SpyModel:
        def classify_task(self, prompt): return "simple"
        def select_model(self, classification=None): ...
        async def generate(self, ctx, request):
            seen.append(request.tool_choice)
            if len(seen) <= 1:
                return _call("echo", {"value": "x"})
            return GenerationResult(text="final", model="m", provider="fake")
        def stream(self, ctx, request): ...

    ts = _tool_service(EchoTool())
    result = await run_agentic_loop(
        _ctx(), model_service=SpyModel(), tool_service=ts, tools=[EchoTool()],
        messages=[Message(role="user", content="go")], config=ToolLoopConfig(max_iterations=1))
    assert seen == ["auto", "none"]
    assert result.text == "final"
    assert result.stop_reason == "max_iterations"
