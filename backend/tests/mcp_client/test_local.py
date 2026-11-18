"""Local MCP servers: one process per start, restart once, a bounded stderr tail, clean stop."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from tests.mcp_client.stdio_server import STDERR_START  # noqa: E402
from zygos.mcp.local import LocalServer, StderrTail  # noqa: E402
from zygos.mcp.results import McpUnavailable  # noqa: E402
from zygos.mcp.types import ServerSpec  # noqa: E402

SERVER_SCRIPT = Path(__file__).with_name("stdio_server.py")


def _spec(tmp_path: Path, *, timeout_s: float = 20.0, env_names=()) -> ServerSpec:
    return ServerSpec(
        name="local",
        transport="stdio",
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
        cwd=str(tmp_path),
        env_names=list(env_names),
        timeout_s=timeout_s,
    )


class Events:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str | None]] = []

    def __call__(self, kind: str, detail: str | None) -> None:
        self.seen.append((kind, detail))

    @property
    def kinds(self) -> list[str]:
        return [kind for kind, _ in self.seen]


async def _until(cond, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not cond():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # A zombie still answers kill(0); it is not running.
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split()[2] != "Z"
    except FileNotFoundError:
        return False


@pytest.fixture
async def make(tmp_path):
    made: list[LocalServer] = []

    def factory(env=None, **kw) -> tuple[LocalServer, Events]:
        events = Events()
        server = LocalServer(_spec(tmp_path, **kw), dict(env or {}), on_event=events)
        made.append(server)
        return server, events

    yield factory
    for server in made:
        await server.stop()


async def test_start_list_call_stop(make):
    server, events = make()
    assert server.status == "not_started"
    await server.start()
    assert server.status == "running"
    assert events.kinds == ["started"]

    listed = await server.list_tools()
    assert {"echo", "crash", "pid", "env", "spam", "grow"} <= {t.name for t in listed.tools}
    assert listed.era  # learned on connect (mode="auto")
    assert all(t.problem is None for t in listed.tools)

    assert await server.call("echo", {"text": "hi"}, 10.0) == "hi"

    await server.stop()
    assert server.status == "stopped"
    assert events.kinds[-1] == "stopped"


async def test_stderr_tail_bounded(make):
    server, _ = make()
    await server.start()
    await _until(lambda: STDERR_START in server.stderr_tail)
    await server.call("spam", {"n": 1000}, 10.0)
    await _until(lambda: server.stderr_tail.endswith("done\n"))
    tail = server.stderr_tail
    assert len(tail.splitlines()) <= 200
    assert len(tail.encode()) <= 16 * 1024
    assert tail.splitlines()[-2:] == ["line 1000", "done"]
    assert STDERR_START not in tail  # the oldest lines were dropped


def test_stderr_tail_capped_by_size():
    # 200 lines of ~100 bytes would be ~20 KB: the 16 KB cap wins.
    tail = StderrTail()
    for i in range(300):
        tail.feed(f"{i:04d} {'x' * 95}\n".encode())
    text = tail.text
    assert len(text.encode()) <= 16 * 1024
    assert len(text.splitlines()) < 200
    assert text.endswith(f"0299 {'x' * 95}\n")
    assert text.startswith("0")  # whole lines kept, no partial first line


def test_stderr_tail_keeps_partial_last_line_and_bad_bytes():
    tail = StderrTail()
    tail.feed(b"one\ntw")
    tail.feed(b"o \xff\xe2\x82")
    tail.feed(b"\xac end")
    assert tail.text == "one\ntwo \ufffd\u20ac end"


async def test_restart_once_then_stopped(make):
    server, events = make()
    await server.start()

    with pytest.raises(McpUnavailable):
        await server.call("crash", {}, 10.0)
    await _until(lambda: "restarted" in events.kinds and server.status == "running")
    assert await server.call("echo", {"text": "back"}, 10.0) == "back"

    with pytest.raises(McpUnavailable):
        await server.call("crash", {}, 10.0)
    await _until(lambda: server.status == "stopped")
    assert server.exit_code == 3
    assert "crash requested" in server.stderr_tail
    assert events.kinds == ["started", "restarted", "started", "stopped"]
    kind, detail = events.seen[-1]
    assert detail is not None and detail.startswith("exit 3")

    # Stays stopped: no more restarts until start() is called again.
    await asyncio.sleep(0.3)
    assert server.status == "stopped"
    with pytest.raises(McpUnavailable):
        await server.call("echo", {"text": "x"}, 5.0)

    await server.start()
    assert server.status == "running"
    assert await server.call("echo", {"text": "again"}, 10.0) == "again"


async def test_crash_at_start_stops_after_one_retry(make):
    server, events = make(env={"CRASH_AT_START": "1"})
    await server.start()
    assert server.status == "stopped"
    assert server.exit_code == 3
    assert events.kinds == ["restarted", "stopped"]
    assert "crashing at start" in server.stderr_tail
    assert events.seen[-1][1] == "exit 3: crashing at start"


async def test_call_on_stopped_raises_unavailable(make):
    server, _ = make()
    with pytest.raises(McpUnavailable):
        await server.call("echo", {"text": "x"}, 5.0)
    with pytest.raises(McpUnavailable):
        await server.list_tools()
    await server.start()
    await server.stop()
    with pytest.raises(McpUnavailable):
        await server.call("echo", {"text": "x"}, 5.0)
    with pytest.raises(McpUnavailable):
        await server.list_tools()


async def test_stop_idempotent_and_no_orphan(make):
    server, events = make()
    await server.start()
    pid = int(await server.call("pid", {}, 10.0))
    assert _alive(pid)
    await server.stop()
    assert not _alive(pid)
    await server.stop()
    assert server.status == "stopped"
    assert events.kinds.count("stopped") == 1


async def test_env_reaches_process(make):
    server, _ = make(env={"ZYGOS_TEST_TOKEN": "s3cr3t-value"}, env_names=["ZYGOS_TEST_TOKEN"])
    await server.start()
    assert await server.call("env", {"name": "ZYGOS_TEST_TOKEN"}, 10.0) == "s3cr3t-value"
    # The safe default environment comes along (PATH), the rest of ours does not.
    assert await server.call("env", {"name": "PATH"}, 10.0) == os.environ.get("PATH", "")
    assert await server.call("env", {"name": "PYTEST_CURRENT_TEST"}, 10.0) == ""


async def test_env_values_never_in_tail_or_events(make):
    secret = "hunter2-very-secret"
    server, events = make(env={"CRASH_AT_START": "1", "LEAKY": secret})
    await server.start()
    assert server.status == "stopped"
    assert "leaky=***" in server.stderr_tail  # the server printed it; we hide it
    assert secret not in server.stderr_tail
    assert all(secret not in (detail or "") for _, detail in events.seen)


async def test_tools_changed_event(make):
    server, events = make()
    await server.start()
    await server.call("grow", {}, 10.0)
    await _until(lambda: "tools_changed" in events.kinds)
    assert "grown" in {t.name for t in (await server.list_tools()).tools}


async def test_spawn_failure_fails_without_restart(tmp_path):
    events = Events()
    server_bad = LocalServer(
        ServerSpec(name="nope", transport="stdio", command=str(tmp_path / "no-such-command"), cwd=str(tmp_path)),
        {},
        on_event=events,
    )
    await server_bad.start()
    assert server_bad.status == "stopped"
    assert server_bad.exit_code is None
    assert events.kinds == ["failed"]
    await server_bad.stop()


async def test_silent_server_fails_after_one_retry(tmp_path):
    # A process that never answers: each attempt gives up after timeout_s and kills it.
    events = Events()
    spec = ServerSpec(
        name="silent",
        transport="stdio",
        command=sys.executable,
        args=["-c", "import time; time.sleep(60)"],
        cwd=str(tmp_path),
        timeout_s=1.0,
    )
    server = LocalServer(spec, {}, on_event=events)
    try:
        await server.start()
        assert server.status == "stopped"
        assert server.exit_code is None
        assert events.kinds == ["restarted", "failed"]
        assert events.seen[-1][1] == "no answer within 1 s"
    finally:
        await server.stop()


async def test_handshake_era_change_notification_counts_once():
    # Handshake-era servers send plain notifications; modern ones use the listen stream
    # (the SDK passes those to the message handler as well, so they're ignored there).
    from mcp_types import ToolListChangedNotification

    events = Events()
    server = LocalServer(ServerSpec(name="h", transport="stdio", command="unused"), {}, on_event=events)
    note = ToolListChangedNotification()
    server._era = "2025-11-25"
    await server._on_message(note)
    server._era = "2026-07-28"
    await server._on_message(note)
    assert events.kinds == ["tools_changed"]
