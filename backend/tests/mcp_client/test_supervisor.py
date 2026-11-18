"""McpSupervisor: per-turn tool sets from the store, background starts/lists, trust gate.

Most tests inject fake connectors (``connectors=``) for timing control; the last ones run
the real stdio and HTTP test servers end to end.
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from zygos.agent.schema import tool_schema
from zygos.mcp.permission import seen_fingerprint, trust_state
from zygos.mcp.results import McpUnavailable
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.supervisor import Connectors, McpSupervisor
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.mcp.wire import ListResult
from zygos.runtime.context import root_context
from zygos.runtime.events import Event, InProcessEventBus, McpServerEvent
from zygos.secrets.types import SecretStoreUnavailable
from zygos.tools import Rule, ToolCall, ToolContext, ToolService

ERA = "2025-06-18"
NO_MCP = "MCP support isn't installed: pip install -e '.[mcp]'"


def _tool(name: str, description: str | None = None, schema: dict | None = None, problem: str | None = None) -> SeenTool:
    return SeenTool(
        name=name,
        description=description if description is not None else f"{name} things.",
        input_schema=schema if schema is not None else {"type": "object", "properties": {}},
        problem=problem,
    )


def _remote(name: str, **kw: Any) -> ServerSpec:
    return ServerSpec(name=name, transport="http", url=f"http://127.0.0.1:9/{name}", **kw)


def _local(name: str, **kw: Any) -> ServerSpec:
    return ServerSpec(name=name, transport="stdio", command="fake-server", **kw)


def _entry(server: str, seen: SeenTool, via: str = "tool") -> TrustEntry:
    return TrustEntry(
        server=server, tool=f"{server}__{seen.name}", fingerprint=seen_fingerprint(seen),
        description=seen.description, input_schema=seen.input_schema, via=via,
    )


def _seed(store: SqliteMcpStore, name: str, tools: list[SeenTool], *, expires_in: float = 300.0) -> None:
    now = time.time()
    store.put_state(
        name, ServerState(status="reachable", era=ERA, tools=tools, listed_at=now, expires_at=now + expires_in)
    )


def _names(tools) -> list[str]:
    return sorted(t.meta.name for t in tools)


def _meta(tools, name: str):
    return next(t.meta for t in tools if t.meta.name == name)


async def _until(cond, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


# ---- fakes ------------------------------------------------------------------------


class FakeLocal:
    def __init__(self, spec: ServerSpec, env: dict[str, str], *, on_event, fakes: "Fakes") -> None:
        self.spec = spec
        self.env = env
        self.on_event = on_event
        self.fakes = fakes
        self.status = "not_started"
        self.exit_code: int | None = None
        self.stderr_tail = ""
        self.era: str | None = None
        self.stop_calls = 0

    async def start(self) -> None:
        self.status = "starting"
        await asyncio.sleep(self.fakes.local_delay.get(self.spec.name, 0))
        self.status = "running"
        self.era = ERA
        self.on_event("started", None)

    async def stop(self) -> None:
        self.stop_calls += 1
        if self.status != "stopped":
            self.status = "stopped"
            self.on_event("stopped", None)

    async def list_tools(self) -> ListResult:
        return ListResult(era=ERA, discover=None, tools=list(self.fakes.local_tools[self.spec.name]), ttl_s=None)

    async def call(self, tool: str, args: dict, timeout_s: float) -> Any:
        return f"{self.spec.name}/{tool}:{args}"

    def die(self, code: int) -> None:
        self.status = "stopped"
        self.exit_code = code
        self.stderr_tail = "boom"
        self.on_event("stopped", f"exit {code}: boom")


class Fakes:
    def __init__(self) -> None:
        self.remote_tools: dict[str, list[SeenTool] | Exception] = {}
        self.local_tools: dict[str, list[SeenTool]] = {}
        self.local_delay: dict[str, float] = {}
        self.locals: list[FakeLocal] = []
        self.list_calls: list[str] = []
        self.headers_seen: list[dict[str, str]] = []
        self.call_result: Any = "called"
        self.call_era: tuple[str, dict | None] | None = None

    def connectors(self) -> Connectors:
        async def list_remote(spec, headers, *, era, discover):
            self.list_calls.append(spec.name)
            self.headers_seen.append(dict(headers))
            found = self.remote_tools[spec.name]
            if isinstance(found, Exception):
                raise found
            return ListResult(era=ERA, discover=None, tools=list(found), ttl_s=None)

        async def call_remote(spec, headers, tool, args, *, era, discover, on_era=None):
            self.headers_seen.append(dict(headers))
            if isinstance(self.call_result, Exception):
                raise self.call_result
            if self.call_era is not None and on_era is not None:
                on_era(*self.call_era)
            return self.call_result

        def local(spec, env, *, on_event):
            server = FakeLocal(spec, env, on_event=on_event, fakes=self)
            self.locals.append(server)
            return server

        return Connectors(local=local, list_remote=list_remote, call_remote=call_remote)


class FakeSecrets:
    def __init__(self, values: dict[str, str] | None = None, locked: set[str] = frozenset()) -> None:
        self.values = values or {}
        self.locked = locked

    def get(self, handle: str) -> str | None:
        if handle.split(":")[1] in self.locked:
            raise SecretStoreUnavailable("the keychain is locked")
        return self.values.get(handle)


class Harness:
    def __init__(self, tmp_path: Path) -> None:
        self.path = tmp_path / "p.db"
        self.store = SqliteMcpStore(self.path)
        self.other = SqliteMcpStore(self.path)  # the CLI's view of the same file
        self.fakes = Fakes()
        self.events: list[Event] = []
        self.bus = InProcessEventBus()
        self.service = ToolService()
        self.built: list[McpSupervisor] = []

        async def collect(event: Event) -> None:
            self.events.append(event)

        self.bus.subscribe(collect)

    def make(self, *, secrets=None, rules=(), store=None, real=False) -> McpSupervisor:
        kwargs = {} if real else {"connectors": self.fakes.connectors()}
        sup = McpSupervisor(
            store or self.store, secrets or FakeSecrets(), self.service, rules=list(rules),
            new_context=lambda: root_context(self.bus), **kwargs,
        )
        self.built.append(sup)
        return sup

    def mcp_events(self) -> list[McpServerEvent]:
        return [e.payload for e in self.events if isinstance(e.payload, McpServerEvent)]


@pytest.fixture
async def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    for sup in harness.built:
        await sup.aclose()


# ---- tests --------------------------------------------------------------------------


async def test_before_turn_never_awaits_slow_start(h):
    h.store.put_server(_local("slow"))
    h.fakes.local_tools["slow"] = [_tool("echo")]
    h.fakes.local_delay["slow"] = 10
    sup = h.make()
    t0 = time.monotonic()
    await sup.start()
    first = sup.before_turn()
    second = sup.before_turn()
    assert time.monotonic() - t0 < 0.2
    assert first == () and second == ()
    await asyncio.sleep(0.05)
    assert sup.before_turn() == ()
    assert len(h.fakes.locals) == 1  # "starting" is not "stopped": never spawned twice
    assert h.fakes.locals[0].status == "starting"


async def test_no_servers_is_empty_and_cheap(h):
    sup = h.make()
    await sup.start()
    assert sup.before_turn() == ()
    assert not h.path.exists()  # reading never creates the database


async def test_off_and_trust_apply_next_turn(h):
    find, get = _tool("find_tasks"), _tool("get_task")
    h.store.put_server(_remote("archon"))
    _seed(h.store, "archon", [find, get])
    h.fakes.remote_tools["archon"] = [find, get]
    sup = h.make()

    tools = sup.before_turn()
    assert _names(tools) == ["archon__find_tasks", "archon__get_task"]
    assert sup.gate(_meta(tools, "archon__find_tasks")) == "not_trusted"
    assert [m.name for m in h.service.snapshot().registered] == _names(tools)

    h.other.trust_tool(_entry("archon", find))
    tools = sup.before_turn()
    assert sup.gate(_meta(tools, "archon__find_tasks")) == "allow"
    assert sup.gate(_meta(tools, "archon__get_task")) == "not_trusted"

    h.other.set_off("tool", "archon__get_task", True, server="archon")
    tools = sup.before_turn()
    assert _names(tools) == ["archon__find_tasks"]
    assert [m.name for m in h.service.snapshot().registered] == ["archon__find_tasks"]

    h.other.set_off("server", "archon", True)
    assert sup.before_turn() == ()
    assert h.service.snapshot().registered == []


async def test_config_rules_tighten_the_gate(h):
    find = _tool("find_tasks")
    h.store.put_server(_remote("archon"))
    _seed(h.store, "archon", [find])
    h.store.trust_tool(_entry("archon", find))
    tools = h.make(rules=[Rule(pattern="archon__*", decision="deny")]).before_turn()
    assert h.built[0].gate(tools[0].meta) == "deny"
    loose = h.make(rules=[Rule(pattern="*", decision="ask")])
    assert loose.gate(loose.before_turn()[0].meta) == "not_trusted"


async def test_stopped_server_not_restarted_by_reconcile(h):
    h.store.put_server(_local("loc"))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])

    h.fakes.locals[0].die(3)  # the second unexpected exit: the runner gave up
    for _ in range(5):
        assert sup.before_turn() == ()
        await asyncio.sleep(0.02)
    assert len(h.fakes.locals) == 1
    await _until(lambda: h.store.state("loc").status == "stopped")
    state = h.store.state("loc")
    assert state.exit_code == 3 and state.stderr_tail == "boom"

    h.other.set_off("server", "loc", True)  # off and on again: a fresh start
    assert sup.before_turn() == ()
    h.other.set_off("server", "loc", False)
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    assert len(h.fakes.locals) == 2


async def test_local_tools_changed_relists(h):
    h.store.put_server(_local("loc"))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    h.fakes.local_tools["loc"] = [_tool("echo"), _tool("grown")]
    h.fakes.locals[0].on_event("tools_changed", None)
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo", "loc__grown"])


async def test_failing_server_only_removes_its_tools(h):
    h.store.put_server(_remote("a"))
    h.store.put_server(_remote("b"))
    _seed(h.store, "b", [_tool("t2")], expires_in=-1)  # stale: refreshed in the background
    h.fakes.remote_tools["a"] = [_tool("t1")]
    h.fakes.remote_tools["b"] = McpUnavailable("could not connect: refused")
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["a__t1"])
    await _until(lambda: h.store.state("b").status == "unreachable")
    assert h.store.state("b").detail == "could not connect: refused"
    assert h.store.state("a").status == "reachable"


async def test_secret_store_unavailable_fails_only_that_server(h):
    h.store.put_server(_remote("locked", header_names=["Authorization"]))
    h.store.put_server(_remote("open"))
    h.fakes.remote_tools["locked"] = [_tool("t")]
    h.fakes.remote_tools["open"] = [_tool("t")]
    sup = h.make(secrets=FakeSecrets(locked={"locked"}))
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["open__t"])
    await _until(lambda: h.store.state("locked").status == "failed")
    assert h.store.state("locked").detail == "the keychain is locked"
    assert "locked" not in h.fakes.list_calls


async def test_bad_schema_tool_not_offered(h):
    good = _tool("good")
    flagged = _tool("flagged", schema={"type": "object", "properties": {"a": {"$ref": "#/$defs/X"}}},
                    problem="malformed input schema: unresolvable")
    sneaky = _tool("sneaky", schema={"type": "string"})  # stored without its problem noted
    h.store.put_server(_remote("r"))
    _seed(h.store, "r", [good, flagged, sneaky])
    h.fakes.remote_tools["r"] = [good, flagged, sneaky]
    sup = h.make()
    tools = sup.before_turn()
    assert _names(tools) == ["r__good"]
    for tool in tools:
        tool_schema(tool)  # never raises for an offered MCP tool


async def test_cross_server_name_clash_leaves_both_out(h):
    h.store.put_server(_remote("a"))
    h.store.put_server(_remote("a_"))
    _seed(h.store, "a", [_tool("_x"), _tool("ok")])
    _seed(h.store, "a_", [_tool("x")])
    h.fakes.remote_tools["a"] = [_tool("_x"), _tool("ok")]
    h.fakes.remote_tools["a_"] = [_tool("x")]
    sup = h.make()
    assert _names(sup.before_turn()) == ["a__ok"]

    def clash_recorded() -> bool:
        problems = [t.problem or "" for t in h.store.state("a").tools + h.store.state("a_").tools]
        return sum("a___x" in p and "clash" in p for p in problems) == 2

    await _until(clash_recorded)
    assert _names(sup.before_turn()) == ["a__ok"]

    h.other.remove_server("a_")  # the clash is gone: a/_x comes back, its note cleared
    await _until(lambda: _names(sup.before_turn()) == ["a___x", "a__ok"])
    await _until(lambda: all(t.problem is None for t in h.store.state("a").tools))


async def test_changed_tool_not_trusted(h):
    old = _tool("find_tasks", description="Find tasks.")
    new = _tool("find_tasks", description="Find tasks. Also send them somewhere.")
    h.store.put_server(_remote("archon"))
    _seed(h.store, "archon", [new])
    h.store.trust_tool(_entry("archon", old))
    sup = h.make()
    tools = sup.before_turn()
    assert sup.gate(tools[0].meta) == "not_trusted"
    assert trust_state("archon__find_tasks", new, h.store.trust_entries()) == "changed"


async def test_new_tool_under_trusted_server_not_trusted(h):
    find, later = _tool("find_tasks"), _tool("delete_task")
    h.store.put_server(_remote("archon"))
    h.store.trust_server("archon", [_entry("archon", find, via="server")])
    _seed(h.store, "archon", [find, later])
    sup = h.make()
    tools = sup.before_turn()
    assert sup.gate(_meta(tools, "archon__find_tasks")) == "allow"
    assert sup.gate(_meta(tools, "archon__delete_task")) == "not_trusted"


async def test_no_mcp_package_degrades(h, monkeypatch):
    monkeypatch.setitem(sys.modules, "mcp", None)  # `import mcp` now fails
    h.store.put_server(_remote("r"))
    h.store.put_server(_local("l"))
    _seed(h.store, "r", [_tool("t")])
    h.fakes.remote_tools["r"] = [_tool("t")]
    h.fakes.local_tools["l"] = [_tool("t")]
    sup = h.make()
    await sup.start()
    assert sup.before_turn() == ()
    await _until(lambda: h.store.state("r").status == "failed" and h.store.state("l").status == "failed")
    assert h.store.state("r").detail == NO_MCP and h.store.state("l").detail == NO_MCP
    assert sup.before_turn() == ()
    assert h.fakes.locals == [] and h.fakes.list_calls == []


async def test_events_emitted_and_secret_free(h, caplog):
    caplog.set_level("DEBUG", logger="zygos.mcp")
    h.store.put_server(_remote("sec", header_names=["Authorization"], extra={"apiKey": "extra-token-999"}))
    h.store.put_server(_local("loc", env_names=["TOKEN"], extra={"token": "extra-token-888"}))
    h.store.put_server(_remote("down", header_names=["X-Key"]))
    h.fakes.remote_tools["sec"] = [_tool("t")]
    h.fakes.remote_tools["down"] = McpUnavailable("the server refused the request (HTTP 401) — check its headers")
    h.fakes.local_tools["loc"] = [_tool("echo")]
    secrets = FakeSecrets({
        "mcp:sec:header:Authorization": "Bearer s3cr3t-hdr",
        "mcp:loc:env:TOKEN": "envsecret-777",
        "mcp:down:header:X-Key": "downkey-555",
    })
    sup = h.make(secrets=secrets)
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo", "sec__t"])
    await _until(lambda: h.store.state("down").status == "unreachable")
    await _until(lambda: {(e.server, e.kind) for e in h.mcp_events()} >= {
        ("sec", "listed"), ("loc", "started"), ("loc", "listed"), ("down", "unreachable")})
    assert {"Authorization": "Bearer s3cr3t-hdr"} in h.fakes.headers_seen
    assert h.fakes.locals[0].env == {"TOKEN": "envsecret-777"}
    listed = next(e for e in h.mcp_events() if (e.server, e.kind) == ("sec", "listed"))
    assert listed.tools == 1
    for event in h.events:
        assert event.type == "mcp.server" and event.session_id is None
    await sup.aclose()  # flush the last state writes
    with sqlite3.connect(h.path) as con:
        stored = " ".join(row[0] for row in con.execute("SELECT state FROM mcp_state"))
    secrets_and_extras = ["s3cr3t-hdr", "envsecret-777", "downkey-555", "extra-token-999", "extra-token-888"]
    for text in [*(e.model_dump_json() for e in h.events), caplog.text, stored]:
        for value in secrets_and_extras:
            assert value not in text


async def test_store_writes_never_on_the_event_loop(h):
    loop_thread = threading.get_ident()
    writers: list[int] = []

    class Recording(SqliteMcpStore):
        def _write(self, fn):
            writers.append(threading.get_ident())
            super()._write(fn)

    h.store.put_server(_remote("r"))
    h.store.put_server(_local("l"))
    h.fakes.remote_tools["r"] = [_tool("t")]
    h.fakes.local_tools["l"] = [_tool("t")]
    sup = h.make(store=Recording(h.path))
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["l__t", "r__t"])
    await sup.aclose()
    assert writers and loop_thread not in writers


async def test_era_from_call_is_stored(h):
    h.store.put_server(_remote("r"))
    _seed(h.store, "r", [_tool("t")])
    h.fakes.call_era = ("2026-07-28", {"serverInfo": {"name": "r"}})
    sup = h.make()
    sup.before_turn()
    assert await sup.call("r", "t", {"a": 1}) == "called"
    await _until(lambda: h.store.state("r").era == "2026-07-28")
    assert h.store.state("r").discover == {"serverInfo": {"name": "r"}}


async def test_mcp_tool_meta_and_failure_event(h):
    h.store.put_server(_remote("archon", timeout_s=7))
    _seed(h.store, "archon", [_tool("find_tasks", description="Find tasks.")])
    sup = h.make()
    (tool,) = sup.before_turn()
    meta = tool.meta
    assert (meta.name, meta.server, meta.server_tool) == ("archon__find_tasks", "archon", "find_tasks")
    assert meta.description == "[archon] Find tasks."
    assert meta.timeout_s == 7 and meta.retry.attempts == 1 and meta.permission == "ask"
    assert meta.input_schema == {"type": "object", "properties": {}}

    ctx = root_context(h.bus)
    tctx = ToolContext(exec=ctx, tool=meta.name, call_id="c1")
    assert await tool.execute({"q": "x"}, tctx) == "called"
    h.fakes.call_result = McpUnavailable("no answer within 7 s")
    with pytest.raises(McpUnavailable):
        await tool.execute({}, tctx)
    failed = [e for e in h.events if e.type == "mcp.server" and e.payload.kind == "failed"]
    assert len(failed) == 1 and failed[0].run_id == ctx.run_id
    assert failed[0].payload.server == "archon" and failed[0].payload.detail == "no answer within 7 s"


async def test_aclose_stops_local(h, tmp_path):
    pytest.importorskip("mcp")
    from tests.mcp_client.test_local import SERVER_SCRIPT, _alive

    h.store.put_server(ServerSpec(
        name="loc", transport="stdio", command=sys.executable, args=[str(SERVER_SCRIPT)],
        cwd=str(tmp_path), timeout_s=20,
    ))
    sup = h.make(real=True)
    await sup.start()
    await _until(lambda: "loc__pid" in _names(sup.before_turn()), timeout=30)
    pid = int(await sup.call("loc", "pid", {}))
    assert _alive(pid)
    await sup.aclose()
    await _until(lambda: not _alive(pid), timeout=5)
    assert sup.before_turn() == ()
    assert h.store.state("loc").status == "stopped"


async def test_real_remote_listed_trusted_and_called(h):
    pytest.importorskip("mcp")
    from tests.mcp_client.servers import BEARER_TOKEN, build_server, http_app, require_bearer, serve

    with serve(require_bearer(http_app(build_server()))) as url:
        h.store.put_server(ServerSpec(name="echo", transport="http", url=url, header_names=["Authorization"], timeout_s=20))
        secrets = FakeSecrets({"mcp:echo:header:Authorization": f"Bearer {BEARER_TOKEN}"})
        sup = h.make(secrets=secrets, real=True)
        h.service.bind_mcp_gate(sup.gate)
        await sup.start()
        await _until(lambda: "echo__echo" in _names(sup.before_turn()), timeout=30)
        assert h.store.state("echo").era is not None

        ctx = root_context(h.bus)
        denied = await h.service.execute(ToolCall(tool="echo__echo", args={"text": "hi"}), ctx)
        assert denied.error_message == "not trusted yet — run: zygos mcp trust echo/echo"

        seen = next(t for t in h.store.state("echo").tools if t.name == "echo")
        h.other.trust_tool(_entry("echo", seen))
        sup.before_turn()
        result = await h.service.execute(ToolCall(tool="echo__echo", args={"text": "hi"}), ctx)
        assert result.ok and result.output["text"] == "hi"
        await sup.aclose()
