"""zygos doctor: MCP lines (passive without --probe)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime

from zygos.cli.doctor import run_doctor
from zygos.mcp.config import parse_servers
from zygos.mcp.store import ServerState, SqliteMcpStore
from zygos.mcp.supervisor import NO_MCP, SECRET_FAILURE, TOOL_COUNT_WARNING
from zygos.mcp.types import SeenTool
from zygos.runtime.bootstrap import build_runtime

URL = "http://127.0.0.1:9/mcp"


def _write(tmp_path):
    cfg = tmp_path / "config.yaml"
    db = tmp_path / ".zygos" / "preferences.db"
    cfg.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    return cfg, db


def _spec(name, **extra):
    body = {"command": "srv", "args": ["--x"]} if "url" not in extra else {}
    return parse_servers(__import__("json").dumps({name: {**body, **extra}}))[0].spec


def _tool(name):
    return SeenTool(name=name, description="d", input_schema={"type": "object"})


def _doctor(cfg, *, probe=False, **kw):
    async def go():
        runtime = build_runtime(cfg)
        try:
            return await run_doctor(runtime, probe=probe, gpu_query=lambda: None, **kw)
        finally:
            await runtime.aclose()

    return asyncio.run(go())


def _mcp(report):
    return [c for c in report.checks if c.name.startswith("mcp")]


def test_no_servers_no_lines(tmp_path):
    cfg, db = _write(tmp_path)
    report = _doctor(cfg)
    assert _mcp(report) == []
    assert not db.exists()


def test_local_status_lines(tmp_path):
    cfg, db = _write(tmp_path)
    store = SqliteMcpStore(db)
    ts = datetime(2026, 11, 18, 14, 2).timestamp()
    for name, state in (
        ("a", ServerState(status="running", status_at=ts)),
        ("b", ServerState(status="stopped", exit_code=3, stderr_tail="x\nboom bad\n", status_at=ts)),
        ("c", ServerState()),
    ):
        store.put_server(_spec(name))
        store.put_state(name, state)
    lines = {c.name: c for c in _mcp(_doctor(cfg))}
    assert lines["mcp:a"].detail == "running (as of 14:02, from zygos serve)"
    assert lines["mcp:b"].detail == "stopped — exit 3: boom bad"
    assert lines["mcp:b"].warn and lines["mcp:b"].ok
    assert lines["mcp:c"].detail == "not started — zygos serve starts it"
    assert all(c.ok for c in lines.values())


def test_remote_line_passive_no_connection(tmp_path):
    cfg, db = _write(tmp_path)
    store = SqliteMcpStore(db)
    store.put_server(_spec("r", url=URL))
    store.put_state("r", ServerState(era="2025-06-18", status="reachable"))
    calls = []

    async def spy(*a, **k):
        calls.append(a)

    report = _doctor(cfg, list_remote=spy)
    assert calls == []
    line = {c.name: c for c in _mcp(report)}["mcp:r"]
    assert line.detail == f"{URL} (protocol 2025-06-18)"


def test_probe_reports_reachable_and_unreachable(tmp_path):
    cfg, db = _write(tmp_path)
    store = SqliteMcpStore(db)
    for n in ("up", "down", "slow"):
        store.put_server(_spec(n, url=URL))

    class R:
        era = "2025-06-18"
        tools = [_tool("a"), _tool("b")]

    async def fake(spec, headers, *, era, discover):
        if spec.name == "up":
            return R()
        if spec.name == "slow":
            await asyncio.sleep(60)
        raise RuntimeError("secret-ish")

    t0 = time.monotonic()
    lines = {c.name: c for c in _mcp(_doctor(cfg, probe=True, list_remote=fake, probe_timeout_s=0.2))}
    assert time.monotonic() - t0 < 5
    assert lines["mcp:up"].detail.endswith("reachable, 2 tools") and not lines["mcp:up"].warn
    assert lines["mcp:down"].detail.endswith("not reachable: RuntimeError") and lines["mcp:down"].warn
    assert "not reachable: no answer within" in lines["mcp:slow"].detail
    assert "secret-ish" not in lines["mcp:down"].detail


def test_mcp_extra_missing_warns(tmp_path):
    cfg, db = _write(tmp_path)
    SqliteMcpStore(db).put_server(_spec("a"))
    lines = _mcp(_doctor(cfg, mcp_installed=lambda: False))
    extra = [c for c in lines if c.name == "mcp"]
    assert len(extra) == 1 and extra[0].warn and extra[0].ok
    assert NO_MCP in extra[0].detail


def test_tool_count_warning(tmp_path):
    cfg, db = _write(tmp_path)
    store = SqliteMcpStore(db)
    store.put_server(_spec("a"))
    store.put_state("a", ServerState(status="running", tools=[_tool(f"t{i}") for i in range(21)]))
    line = {c.name: c for c in _mcp(_doctor(cfg))}["mcp_tools"]
    assert line.detail.startswith("21 on") and TOOL_COUNT_WARNING in line.detail and line.warn
    store.set_off("server", "a", True)
    line = {c.name: c for c in _mcp(_doctor(cfg))}["mcp_tools"]
    assert line.detail == "0 on" and not line.warn


def test_secret_failure_hint(tmp_path):
    cfg, db = _write(tmp_path)
    store = SqliteMcpStore(db)
    store.put_server(_spec("a"))
    store.put_state("a", ServerState(status="failed", detail=SECRET_FAILURE + "locked"))
    line = {c.name: c for c in _mcp(_doctor(cfg))}["mcp:a"]
    assert "zygos mcp off/on a" in line.detail and "unlocking the secret store" in line.detail


def test_unreadable_record_is_one_warn(tmp_path):
    cfg, db = _write(tmp_path)
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b"not a sqlite file" * 100)
    lines = _mcp(_doctor(cfg))
    assert len(lines) == 1 and lines[0].warn and lines[0].ok


# ---- probing a server that needs a header from the secret store -------------------

import pytest  # noqa: E402

TOKEN_HEADER = "Bearer t0k"


def _write_file_store(tmp_path):
    cfg, db = _write(tmp_path)
    cfg.write_text(cfg.read_text() + "secrets:\n  backend: encrypted_file\n")
    return cfg, db


def _auth_spec(url, name="r"):
    return parse_servers(__import__("json").dumps({name: {"url": url, "headers": {"Authorization": TOKEN_HEADER}}}))[0].spec


def test_probe_uses_stored_header_secret(tmp_path):
    pytest.importorskip("cryptography")
    pytest.importorskip("mcp")
    from tests.mcp_client.servers import build_server, http_app, require_bearer, serve

    cfg, db = _write_file_store(tmp_path)
    with serve(require_bearer(http_app(build_server()))) as url:
        SqliteMcpStore(db).put_server(_auth_spec(url))

        async def go():
            runtime = build_runtime(cfg)
            try:
                runtime.secrets.set("mcp:r:header:Authorization", TOKEN_HEADER)
                return await run_doctor(runtime, probe=True, gpu_query=lambda: None)
            finally:
                await runtime.aclose()

        report = asyncio.run(go())
    line = {c.name: c for c in _mcp(report)}["mcp:r"]
    assert "reachable, " in line.detail and "not reachable" not in line.detail and not line.warn
    assert "t0k" not in " ".join(c.detail for c in report.checks)


def test_probe_missing_header_secret_is_not_checked(tmp_path):
    pytest.importorskip("cryptography")
    cfg, db = _write_file_store(tmp_path)
    SqliteMcpStore(db).put_server(_auth_spec(URL))
    calls = []

    async def spy(*a, **k):
        calls.append(a)

    report = _doctor(cfg, probe=True, list_remote=spy)
    line = {c.name: c for c in _mcp(report)}["mcp:r"]
    assert calls == []
    assert "not checked: needs Authorization from the secret store (" in line.detail and line.warn


def test_secret_failure_marker_end_to_end(tmp_path):
    """A supervisor failure for secret reasons carries the shared marker; doctor hints on it."""
    from zygos.mcp.supervisor import SECRET_FAILURE
    from zygos.secrets import SecretStoreError

    cfg, db = _write(tmp_path)
    SqliteMcpStore(db).put_server(_spec("a", env={"KEY": "v"}))

    async def go():
        runtime = build_runtime(cfg)
        try:
            def boom(handle):
                raise SecretStoreError("locked")

            runtime.mcp._secrets = type("S", (), {"get": staticmethod(boom)})()
            runtime.mcp._reload()
            entry = runtime.mcp._servers["a"]
            await runtime.mcp._start_local(entry)
            return entry.state
        finally:
            await runtime.aclose()

    state = asyncio.run(go())
    assert state.detail.startswith(SECRET_FAILURE)
    SqliteMcpStore(db).put_state("a", state.model_copy(update={"status": "failed"}))
    line = {c.name: c for c in _mcp(_doctor(cfg))}["mcp:a"]
    assert "zygos mcp off/on a" in line.detail
