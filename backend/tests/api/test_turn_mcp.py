"""MCP tools in a turn: the per-turn tool set, the frames' ``server`` field, and the
server lifespan starting the supervisor without ever blocking startup."""

from __future__ import annotations

import asyncio
import dataclasses
import time
from pathlib import Path

import pytest

from tests.api.test_turn_tools import EchoTool, _call, _drain, _model, _session
from zygos.agent.config import ToolLoopConfig
from zygos.api.app import create_app
from zygos.api.frames import TOOLS
from zygos.api.turn import TurnDeps, run_turn
from zygos.config.schema import ReasoningConfig
from zygos.mcp.permission import seen_fingerprint
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.supervisor import McpSupervisor
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.reasoning.service import DefaultReasoningService
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.service import ToolService


class _NoSecrets:
    def get(self, handle: str) -> str | None:
        return None


def _supervisor(db: Path, service: ToolService) -> McpSupervisor:
    sup = McpSupervisor(
        SqliteMcpStore(db), _NoSecrets(), service, rules=[],
        new_context=lambda: root_context(InProcessEventBus()),
    )
    service.bind_mcp_gate(sup.gate)
    return sup


def _deps(model, service: ToolService, *, tools=(), tools_for_turn=None) -> TurnDeps:
    return TurnDeps(
        model_service=model,
        reasoning_factory=lambda: DefaultReasoningService(model, ReasoningConfig(enabled=True, profile="shallow")),
        reasoning_enabled=False,
        memory_service=None,
        new_id=lambda: "turn-1",
        tool_service=service,
        tools=tuple(tools),
        tool_loop_config=ToolLoopConfig(),
        tools_for_turn=tools_for_turn,
    )


def _shape(frames):
    return [(f.channel, f.type, f.payload) for f in frames]


async def _turn(deps: TurnDeps, text: str = "go"):
    session = _session()
    await run_turn(session, deps, text, CancelToken(), spoken_input=False, think=None)
    return _drain(session)


async def test_no_servers_turn_unchanged(tmp_path):
    db = tmp_path / "p.db"
    # A built-in tool turn: frames byte-identical, no "server" key.
    service = ToolService()
    service.register(EchoTool())
    baseline = await _turn(_deps(_model([_call("echo", {"value": "hi"}), "done"]), service, tools=(EchoTool(),)))

    service = ToolService()
    echo = EchoTool()
    service.register(echo)
    sup = _supervisor(db, service)
    try:
        wired = await _turn(_deps(
            _model([_call("echo", {"value": "hi"}), "done"]), service, tools=(echo,),
            tools_for_turn=lambda: (echo,) + sup.before_turn(),
        ))
        assert _shape(wired) == _shape(baseline)
        assert all("server" not in f.payload for f in wired if f.channel == TOOLS)

        # No tools at all: still the streaming path (chat:token frames), as today.
        service = ToolService()
        plain = await _turn(_deps(_model(["alpha beta"]), service))
        sup2 = _supervisor(db, service)
        wired_plain = await _turn(_deps(_model(["alpha beta"]), service, tools_for_turn=lambda: () + sup2.before_turn()))
        assert _shape(wired_plain) == _shape(plain)
        assert any(f.type == "token" for f in wired_plain)
        await sup2.aclose()
    finally:
        await sup.aclose()
    assert not db.exists()


def _seed_listed(db: Path, name: str, tools: list[SeenTool]) -> None:
    store = SqliteMcpStore(db)
    store.put_server(ServerSpec(name=name, transport="http", url="http://127.0.0.1:9/mcp"))
    now = time.time()
    store.put_state(name, ServerState(status="reachable", tools=tools, listed_at=now, expires_at=now + 3600))


async def test_untrusted_tool_turn_finishes_fast(tmp_path):
    pytest.importorskip("mcp")  # the supervisor offers no tools without the SDK installed
    db = tmp_path / "p.db"
    _seed_listed(db, "echo", [SeenTool(name="echo", description="Echo.",
                                       input_schema={"type": "object", "properties": {"text": {"type": "string"}}})])
    service = ToolService()
    sup = _supervisor(db, service)
    try:
        t0 = time.monotonic()
        frames = await _turn(_deps(
            _model([_call("echo__echo", {"text": "hi"}), "ok then"]), service,
            tools_for_turn=lambda: () + sup.before_turn(),
        ))
        assert time.monotonic() - t0 < 2.0
    finally:
        await sup.aclose()
    call = next(f for f in frames if f.channel == TOOLS and f.type == "call")
    result = next(f for f in frames if f.channel == TOOLS and f.type == "result")
    assert call.payload["server"] == "echo"
    assert result.payload["server"] == "echo"
    assert result.payload["ok"] is False
    assert result.payload["error_code"] == "tool_permission_denied"
    assert result.payload["error_message"] == (
        "not trusted — answer the prompt in the web page, or run: zygos mcp trust echo/echo")
    assert frames[-1].type == "turn.end" and frames[-1].payload["text"] == "ok then"


class _McpEcho:
    """An MCP-shaped tool (``meta.server`` set) without a live server."""

    def __init__(self) -> None:
        from zygos.tools import ToolMeta

        self.meta = ToolMeta(name="echo__echo", description="[echo] Echo.",
                             input_schema={"type": "object"}, server="echo",
                             server_tool="echo", permission="ask")
        self.calls = 0

    async def execute(self, input, ctx):
        self.calls += 1
        return {"echoed": input}


async def test_untrusted_tool_prompts_then_runs_and_frames_in_order():
    from zygos.api.permission import PromptAnswer, WebSocketPromptResolver
    from zygos.api.session import SessionRegistry
    from zygos.tools import BaseTool

    class Tool(_McpEcho, BaseTool):
        pass

    registry = SessionRegistry(new_context=lambda sid: root_context(InProcessEventBus(), session_id=sid),
                               clock=lambda: 0.0, new_id=lambda: "s1")
    session = registry.create()
    session.connected = True
    tool = Tool()
    service = ToolService(mcp_gate=lambda meta: "not_trusted")
    service.bind_mcp_describe(lambda meta: {"server": "echo", "server_tool": "echo", "can_trust": True})
    service.bind_resolver(WebSocketPromptResolver(registry, timeout_s=5.0))
    service.register(tool)

    async def click_allow():
        while not session.pending_permissions:
            await asyncio.sleep(0)
        next(iter(session.pending_permissions.values())).set_result(PromptAnswer("allow", None))

    clicker = asyncio.create_task(click_allow())
    deps = _deps(_model([_call("echo__echo", {"text": "hi"}), "it said hi"]), service, tools=(tool,))
    await asyncio.wait_for(run_turn(session, deps, "go", CancelToken(), spoken_input=False, think=None), 5.0)
    await clicker
    frames = [f for f in _drain(session) if f.channel == TOOLS]
    assert [f.type for f in frames] == ["call", "permission", "permission.result", "result"]
    call, prompt, outcome, result = frames
    assert prompt.payload["call_id"] == call.payload["call_id"] == result.payload["call_id"]
    assert prompt.payload["server_tool"] == "echo" and prompt.payload["can_trust"] is True
    assert outcome.payload == {"call_id": call.payload["call_id"], "outcome": "allowed"}
    assert result.payload["ok"] is True and tool.calls == 1


async def _until(cond, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.05)


async def test_trusted_remote_tool_called_in_turn(tmp_path):
    pytest.importorskip("mcp")
    from tests.mcp_client.servers import build_server, http_app, serve

    db = tmp_path / "p.db"
    store = SqliteMcpStore(db)
    service = ToolService()
    with serve(http_app(build_server())) as url:
        store.put_server(ServerSpec(name="echo", transport="http", url=url, timeout_s=20))
        sup = _supervisor(db, service)
        try:
            await sup.start()
            await _until(lambda: any(t.meta.name == "echo__echo" for t in sup.before_turn()))
            seen = next(t for t in store.state("echo").tools if t.name == "echo")
            store.trust_tool(TrustEntry(
                server="echo", tool="echo__echo", fingerprint=seen_fingerprint(seen),
                description=seen.description, input_schema=seen.input_schema, via="tool",
            ))
            frames = await _turn(_deps(
                _model([_call("echo__echo", {"text": "hi"}), "it said hi"]), service,
                tools_for_turn=lambda: () + sup.before_turn(),
            ))
        finally:
            await sup.aclose()
    result = next(f for f in frames if f.channel == TOOLS and f.type == "result")
    assert result.payload["ok"] is True, result.payload
    assert result.payload["server"] == "echo"
    assert result.payload["tool"] == "echo__echo"
    assert frames[-1].payload["text"] == "it said hi"


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{tmp_path / '.zygos' / 'p.db'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    return cfg


async def test_lifespan_start_failure_does_not_block_startup(tmp_path, caplog):
    runtime = build_runtime(_config(tmp_path))
    real = runtime.mcp
    calls: list[str] = []

    class Broken:
        async def start(self) -> None:
            calls.append("start")
            raise RuntimeError("boom")

        def before_turn(self):
            return ()

        async def aclose(self) -> None:
            calls.append("aclose")
            await real.aclose()

    app = create_app(dataclasses.replace(runtime, mcp=Broken(), memory_service=None))
    async with app.router.lifespan_context(app):
        assert app.state.runtime.lifecycle_stage == "accept_requests"
    assert calls == ["start", "aclose"]
    assert "mcp" in caplog.text.lower() and "boom" not in caplog.text
    assert app.state.runtime.http_client.is_closed


async def test_app_turn_deps_use_supervisor_per_turn(tmp_path):
    runtime = build_runtime(_config(tmp_path))
    calls: list[int] = []
    real = runtime.mcp

    class Counting:
        def before_turn(self):
            calls.append(1)
            return ()

        async def aclose(self) -> None:
            await real.aclose()

    app = create_app(dataclasses.replace(runtime, mcp=Counting()))
    try:
        deps = app.state.turn_deps
        assert deps.tools_for_turn is not None
        assert deps.tools_for_turn() == runtime.tools
        assert calls == [1]
    finally:
        await app.state.runtime.aclose()


async def test_per_turn_tool_failure_keeps_builtins():
    service = ToolService()
    echo = EchoTool()
    service.register(echo)

    def broken():
        raise RuntimeError("supervisor bug")

    frames = await _turn(_deps(_model([_call("echo", {"value": "hi"}), "done"]), service,
                               tools=(echo,), tools_for_turn=broken))
    result = next(f for f in frames if f.channel == TOOLS and f.type == "result")
    assert result.payload["ok"] is True
    assert frames[-1].payload["text"] == "done"


async def test_per_turn_tool_failure_logged_once_until_recovery(caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="zygos.api.turn")
    service = ToolService()
    echo = EchoTool()
    service.register(echo)
    failing = [True]

    def flaky():
        if failing[0]:
            raise RuntimeError("supervisor bug")
        return (echo,)

    def records():
        return [r for r in caplog.records if r.name == "zygos.api.turn" and "tool set" in r.getMessage()]

    for _ in range(3):
        await _turn(_deps(_model(["plain"]), service, tools=(echo,), tools_for_turn=flaky))
    warned = [r for r in records() if r.levelno == logging.WARNING]
    assert len(warned) == 1 and warned[0].exc_info is not None
    quiet = [r for r in records() if r.levelno == logging.DEBUG]
    assert len(quiet) == 2 and all(r.exc_info is None for r in quiet)

    failing[0] = False
    await _turn(_deps(_model(["plain"]), service, tools=(echo,), tools_for_turn=flaky))
    recovered = [r for r in records() if r.levelno == logging.INFO]
    assert len(recovered) == 1
    await _turn(_deps(_model(["plain"]), service, tools=(echo,), tools_for_turn=flaky))
    assert len([r for r in records() if r.levelno == logging.INFO]) == 1


async def test_app_wires_describe_trust_and_announce(tmp_path):
    runtime = build_runtime(_config(tmp_path))
    real = runtime.mcp
    assert runtime.tool_service._mcp_describe == real.describe
    trusted: list[tuple[str, str]] = []

    class Stub:
        def before_turn(self):
            return ()

        async def trust_from_prompt(self, tool, scope):
            trusted.append((tool, scope))
            return True

        async def aclose(self) -> None:
            await real.aclose()

    app = create_app(dataclasses.replace(runtime, mcp=Stub()))
    try:
        resolver = runtime.tool_service._resolver
        assert await resolver._trust("archon__find_tasks", "server") is True
        assert trusted == [("archon__find_tasks", "server")]
        # Announce starts a task and returns at once; silent without a voice service.
        session = app.state.registry.create()
        session.speak = True
        started = resolver._announce(session, "I need your OK on screen to use x.")
        assert isinstance(started, asyncio.Future)
        await started
        assert session.outbound.empty()
    finally:
        await app.state.runtime.aclose()
