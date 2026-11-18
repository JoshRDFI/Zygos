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
    """Is the process running? (A zombie, dead but not yet reaped, counts as gone.)"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc = Path("/proc")
    if not proc.is_dir():  # not Linux: kill(0) is all we can ask
        return True
    try:
        return (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


async def _all_dead(pids: list[int], timeout: float = 5.0) -> bool:
    try:
        await _until(lambda: not any(_alive(p) for p in pids), timeout)
    except AssertionError:
        return False
    return True


def _pids(path: Path) -> list[int]:
    return [int(p) for p in path.read_text().split()] if path.exists() else []


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
    await asyncio.sleep(0.3)
    assert events.kinds.count("tools_changed") == 1  # the SDK hands it over twice; counted once
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


async def test_handshake_era_server_change_notification(make):
    server, events = make(env={"HANDSHAKE_ONLY": "1"})
    await server.start()
    assert server.status == "running"
    assert server.era == "2025-11-25"
    await server.call("grow", {}, 10.0)
    await _until(lambda: "tools_changed" in events.kinds)
    await asyncio.sleep(0.3)
    assert events.kinds.count("tools_changed") == 1
    assert "grown" in {t.name for t in (await server.list_tools()).tools}


async def test_status_starting_and_start_during_restart_waits(make):
    server, events = make()
    starting = asyncio.ensure_future(server.start())
    await asyncio.sleep(0)
    assert server.status == "starting"
    await starting
    assert server.status == "running"

    with pytest.raises(McpUnavailable):
        await server.call("crash", {}, 10.0)
    await _until(lambda: "restarted" in events.kinds)
    assert server.status == "starting"
    await server.start()  # waits for the restart to settle
    assert server.status == "running"
    assert await server.call("echo", {"text": "up"}, 10.0) == "up"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_stop_kills_term_ignoring_grandchild(make, tmp_path, monkeypatch):
    import zygos.mcp.local as local

    monkeypatch.setattr(local, "_KILL_AFTER_S", 1.0)  # the grandchild ignores SIGTERM
    pid_file = tmp_path / "grandchildren"
    server, _ = make(env={"GRANDCHILD_PIDS": str(pid_file)})
    await server.start()
    pids = _pids(pid_file)
    assert len(pids) == 1 and _alive(pids[0])
    await server.stop()
    assert await _all_dead(pids)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_terminate_then_kill_reaches_term_ignoring_grandchild(make, tmp_path, monkeypatch):
    # The leader hangs (survives stdin closing), so the group gets SIGTERM, then SIGKILL.
    import zygos.mcp.local as local

    monkeypatch.setattr(local, "_KILL_AFTER_S", 1.0)
    monkeypatch.setattr(local, "_STDIN_GRACE_S", 0.1)
    pid_file = tmp_path / "grandchildren"
    server, events = make(env={"GRANDCHILD_PIDS": str(pid_file), "HANG": "1"}, timeout_s=0.5)
    await server.start()
    assert events.kinds == ["restarted", "failed"]
    pids = _pids(pid_file)
    assert len(pids) == 2
    assert await _all_dead(pids)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
async def test_crashed_leader_leaves_no_grandchild(make, tmp_path):
    pid_file = tmp_path / "grandchildren"
    server, _ = make(env={"GRANDCHILD_PIDS": str(pid_file)})
    await server.start()
    for _ in range(2):
        await _until(lambda: server.status == "running")
        with pytest.raises(McpUnavailable):
            await server.call("crash", {}, 10.0)
        await _until(lambda: server.status != "running")
    await _until(lambda: server.status == "stopped")
    pids = _pids(pid_file)
    assert len(pids) == 2
    assert await _all_dead(pids)


async def test_cancelled_runner_releases_everything(make):
    import gc
    import warnings

    server, _ = make()
    await server.start()
    pid = int(await server.call("pid", {}, 10.0))
    server._runner.cancel()  # no public way to cancel the runner task itself
    await server.stop()  # does not re-raise the runner's cancellation
    assert server.status == "stopped"
    assert await _all_dead([pid])
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gc.collect()
    assert not [w for w in caught if issubclass(w.category, ResourceWarning)]


async def test_stop_caller_cancellation_still_propagates(make):
    server, _ = make()
    await server.start()
    stopping = asyncio.ensure_future(server.stop())
    await asyncio.sleep(0)
    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    await server.stop()
    assert server.status == "stopped"


async def test_exit_code_stays_readable_when_an_env_value_is_a_digit(make):
    server, events = make(env={"CRASH_AT_START": "1", "N": "3"})
    await server.start()
    assert server.exit_code == 3
    assert events.seen[-1] == ("stopped", "exit 3: crashing at start")


async def test_runner_bug_logged_without_traceback_or_secret(tmp_path, monkeypatch, caplog):
    secret = "hunter2-very-secret"

    async def broken(self, *args):
        raise RuntimeError(f"boom {secret}")

    monkeypatch.setattr(LocalServer, "_run_once", broken)
    events = Events()
    server = LocalServer(_spec(tmp_path), {"TOKEN": secret}, on_event=events)
    with caplog.at_level("DEBUG", logger="zygos.mcp"):
        await server.start()
    assert server.status == "stopped"
    assert events.kinds == ["failed"]
    records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert records and all(r.exc_info is None for r in records)
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in text and secret not in text


# ---- the Windows branch, driven on any OS by standing in for the SDK's win32 helpers --


class _Win32Spy:
    def __init__(self, monkeypatch, *, fallback: bool = False) -> None:
        import mcp.os.win32.utilities as win32

        import zygos.mcp.local as local

        self.calls: list[tuple] = []
        self.fallback = fallback
        monkeypatch.setattr(local, "_on_windows", lambda: True)
        monkeypatch.setattr(win32, "get_windows_executable_command", self.resolve)
        monkeypatch.setattr(win32, "create_windows_process", self.create)
        monkeypatch.setattr(win32, "terminate_windows_process_tree", self.terminate)
        monkeypatch.setattr(win32, "close_process_job", self.close_job)

    def resolve(self, command):
        self.calls.append(("resolve", command))
        return sys.executable if command == "npx" else command

    async def create(self, command, args, env=None, errlog=None, cwd=None):
        import subprocess

        import anyio
        from mcp.os.win32.utilities import FallbackProcess

        self.calls.append(("create", command, list(args), dict(env or {}), errlog, cwd))
        if self.fallback:
            popen = subprocess.Popen(
                [command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errlog, env=env, cwd=cwd,
                bufsize=0,
            )
            return FallbackProcess(popen)
        return await anyio.open_process([command, *args], env=env, stderr=errlog, cwd=cwd)

    async def terminate(self, process):
        self.calls.append(("terminate", process.pid))
        process.terminate()

    def close_job(self, process):
        self.calls.append(("close_job", process.pid))

    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


def _npx_spec(tmp_path: Path, *, args=None, timeout_s: float = 20.0) -> ServerSpec:
    return ServerSpec(
        name="win", transport="stdio", command="npx", args=args or [str(SERVER_SCRIPT)], cwd=str(tmp_path),
        timeout_s=timeout_s,
    )


@pytest.mark.parametrize("fallback", [False, True], ids=["anyio-process", "popen-fallback"])
async def test_windows_branch_uses_sdk_helpers(tmp_path, monkeypatch, fallback):
    import subprocess

    spy = _Win32Spy(monkeypatch, fallback=fallback)
    events = Events()
    server = LocalServer(_npx_spec(tmp_path), {"TOKEN": "tok-value"}, on_event=events)
    try:
        await server.start()
        assert server.status == "running"
        assert await server.call("echo", {"text": "win"}, 10.0) == "win"
        await _until(lambda: STDERR_START in server.stderr_tail)  # stderr piped to the tail
    finally:
        await server.stop()
    assert spy.calls[0] == ("resolve", "npx")
    _, command, args, env, errlog, cwd = spy.calls[1]
    assert (command, args, errlog, cwd) == (sys.executable, [str(SERVER_SCRIPT)], subprocess.PIPE, str(tmp_path))
    assert env["TOKEN"] == "tok-value" and "PATH" in env
    assert "close_job" in spy.kinds()


async def test_windows_branch_terminates_job_tree_when_server_hangs(tmp_path, monkeypatch):
    spy = _Win32Spy(monkeypatch)
    events = Events()
    spec = _npx_spec(tmp_path, args=["-c", "import time; time.sleep(60)"], timeout_s=1.0)
    server = LocalServer(spec.model_copy(update={"command": sys.executable}), {}, on_event=events)
    try:
        await server.start()
    finally:
        await server.stop()
    assert events.kinds == ["restarted", "failed"]
    assert spy.kinds().count("terminate") == 2
    assert spy.kinds().count("close_job") == 2
