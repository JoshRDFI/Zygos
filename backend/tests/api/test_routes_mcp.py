"""The ``/mcp`` routes behind the Tools page (RFC-0015): every action the CLI has, the
same shared logic underneath, and no secret value in any response or log line."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest

from tests.mcp_client.test_supervisor import Fakes
from zygos.api.app import create_app
from zygos.cli.mcp import run_mcp
from zygos.config.loader import load_config
from zygos.mcp import manage
from zygos.mcp.store import ServerState, SqliteMcpStore
from zygos.mcp.supervisor import TOOL_COUNT_WARNING, McpSupervisor
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.runtime.bootstrap import build_runtime
from zygos.secrets import Presence, SecretStoreUnavailable

MARKER = "MARKER-SECRET"
ERA = "2025-06-18"


class PageSecrets:
    """An in-memory secret store; ``hang`` makes presence wait (a locked keychain prompt)."""

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})
        self.hang = threading.Event()
        self.release = threading.Event()
        self.presence_error: Exception | None = None
        self.waiting = 0  # presence calls blocked on ``hang`` right now
        self.most_waiting = 0
        self._lock = threading.Lock()

    def status(self):
        return SimpleNamespace(available=True, why_unavailable=None)

    def get(self, handle):
        return self.values.get(handle)

    def set(self, handle, value):
        self.values[handle] = value

    def delete(self, handle):
        self.values.pop(handle, None)

    def presence(self, handle):
        if self.hang.is_set():
            with self._lock:
                self.waiting += 1
                self.most_waiting = max(self.most_waiting, self.waiting)
            self.release.wait(10)
            with self._lock:
                self.waiting -= 1
        if self.presence_error is not None:
            raise self.presence_error
        return Presence("set" if handle in self.values else "not_set")


def _tool(name: str) -> SeenTool:
    return SeenTool(name=name, description=f"The {name} tool.", input_schema={"type": "object", "properties": {}})


@pytest.fixture
async def page(tmp_path):
    db = tmp_path / ".zygos" / "preferences.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
        "tools:\n  enabled: []\n",
        encoding="utf-8",
    )
    runtime = build_runtime(cfg)
    built_mcp = runtime.mcp
    fakes = Fakes()
    secrets = PageSecrets()
    sup = McpSupervisor(
        SqliteMcpStore(db), secrets, runtime.tool_service, rules=[],
        new_context=runtime.new_context, connectors=fakes.connectors(),
    )
    app = create_app(dataclasses.replace(runtime, mcp=sup, secrets=secrets))
    await sup.start()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    try:
        yield SimpleNamespace(
            client=client, store=SqliteMcpStore(db), other=SqliteMcpStore(db), secrets=secrets,
            fakes=fakes, sup=sup, cfg=cfg, db=db,
        )
    finally:
        secrets.release.set()
        await client.aclose()
        await app.state.runtime.aclose()
        await built_mcp.aclose()


def _remote(name: str, **kw) -> ServerSpec:
    return ServerSpec(name=name, transport="http", url=f"http://127.0.0.1:9/{quote(name, safe='')}", **kw)


def _local(name: str, **kw) -> ServerSpec:
    return ServerSpec(name=name, transport="stdio", command="fake-server", **kw)


def _seed(store: SqliteMcpStore, spec: ServerSpec, tools: list[SeenTool] | None = None) -> None:
    store.put_server(spec)
    if tools is not None:
        now = time.time()
        store.put_state(spec.name, ServerState(
            status="reachable", era=ERA, tools=tools, listed_at=now, expires_at=now + 3600, status_at=now,
        ))


def _server(view: dict, name: str) -> dict:
    return next(s for s in view["servers"] if s["name"] == name)


def _path(name: str) -> str:
    return f"/mcp/servers/{quote(name, safe='')}"


def _paste(servers: dict) -> str:
    return json.dumps({"mcpServers": servers})


# ---- GET /mcp ---------------------------------------------------------------------------


async def test_get_mcp_shows_presence_never_values(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"], env_names=["KEY"]), [_tool("find")])
    page.secrets.values["mcp:arch:header:Authorization"] = f"Bearer {MARKER}"
    resp = await page.client.get("/mcp")
    assert resp.status_code == 200
    server = _server(resp.json(), "arch")
    assert server["secrets"] == {"Authorization": "set", "KEY": "not set"}
    assert [t["zname"] for t in server["tools"]] == ["arch__find"]
    assert resp.json()["installed"] is True
    assert MARKER not in resp.text


async def test_get_mcp_empty(page):
    resp = await page.client.get("/mcp")
    assert resp.status_code == 200
    assert resp.json()["servers"] == [] and resp.json()["tools_on"] == 0
    assert not page.db.exists()  # reading never creates the record


async def test_get_mcp_not_installed(page, monkeypatch):
    monkeypatch.setattr(manage, "mcp_installed", lambda: False)
    _seed(page.store, _remote("arch"), [_tool("find")])
    resp = await page.client.get("/mcp")
    assert resp.status_code == 200
    assert resp.json()["installed"] is False
    assert [s["name"] for s in resp.json()["servers"]] == ["arch"]


async def test_get_mcp_bounded_when_secret_store_hangs(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    page.secrets.hang.set()
    t0 = time.monotonic()
    resp = await page.client.get("/mcp")
    assert time.monotonic() - t0 < 7.0
    assert resp.status_code == 200
    server = _server(resp.json(), "arch")
    assert server["secrets"] == {"Authorization": "unknown"}
    assert server["secrets_note"] == "the secret store didn't answer in time"


async def test_get_mcp_hung_secret_store_blocks_one_thread_only(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    page.secrets.values["mcp:arch:header:Authorization"] = MARKER
    page.secrets.hang.set()
    took = []
    for _ in range(3):
        t0 = time.monotonic()
        resp = await page.client.get("/mcp")
        took.append(time.monotonic() - t0)
        assert resp.status_code == 200
        assert _server(resp.json(), "arch")["secrets"] == {"Authorization": "unknown"}
    assert took[0] < 7.0
    assert took[1] < 2.0 and took[2] < 2.0  # the hung read is still in flight: not asked again
    assert page.secrets.most_waiting == 1
    page.secrets.hang.clear()
    page.secrets.release.set()
    await _until(lambda: page.secrets.waiting == 0)
    await asyncio.sleep(0.05)
    resp = await page.client.get("/mcp")  # the store answers again: asked afresh
    assert _server(resp.json(), "arch")["secrets"] == {"Authorization": "set"}


_HUNG_CHILD = textwrap.dedent("""
    import asyncio, dataclasses, sys, threading
    from pathlib import Path
    from types import SimpleNamespace
    import httpx
    from zygos.api import routes_mcp
    from zygos.api.app import create_app
    from zygos.mcp.store import SqliteMcpStore
    from zygos.mcp.types import ServerSpec
    from zygos.runtime.bootstrap import build_runtime

    class Hung:
        def status(self):
            return SimpleNamespace(available=True, why_unavailable=None)
        def presence(self, handle):
            threading.Event().wait()  # a keychain prompt nobody answers

    async def main(cfg, db):
        SqliteMcpStore(db).put_server(ServerSpec(
            name="arch", transport="http", url="http://127.0.0.1:9/mcp", header_names=["Authorization"]))
        routes_mcp._VIEW_LIMIT_S = 0.5
        runtime = build_runtime(Path(cfg))
        app = create_app(dataclasses.replace(runtime, secrets=Hung()))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
            resp = await client.get("/mcp")
        print("answered", resp.status_code, resp.json()["servers"][0]["secrets"], flush=True)
        await app.state.runtime.aclose()

    asyncio.run(main(sys.argv[1], sys.argv[2]))
""")


def test_hung_secret_store_never_keeps_the_process_alive(tmp_path):
    db = tmp_path / ".zygos" / "preferences.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
        "tools:\n  enabled: []\n",
        encoding="utf-8",
    )
    script = tmp_path / "child.py"
    script.write_text(_HUNG_CHILD, encoding="utf-8")
    env = {**os.environ, "ZYGOS_HOME": str(tmp_path / "home")}
    try:
        done = subprocess.run(
            [sys.executable, str(script), str(cfg), str(db)], cwd=Path(__file__).resolve().parents[2],
            env=env, capture_output=True, text=True, timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
        raise AssertionError(f"the process didn't exit with a read still hung (stdout: {out!r})") from None
    assert done.returncode == 0, done.stderr[-2000:]
    assert "answered 200 {'Authorization': 'unknown'}" in done.stdout


async def test_get_mcp_presence_failure_reads_unknown_by_type_name(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    page.secrets.presence_error = RuntimeError(f"backend said {MARKER}")
    resp = await page.client.get("/mcp")
    assert resp.status_code == 200
    server = _server(resp.json(), "arch")
    assert server["secrets"] == {"Authorization": "unknown"}
    assert server["secret_reasons"] == {"Authorization": "RuntimeError"}
    assert MARKER not in resp.text


async def test_get_mcp_secret_store_error_keeps_its_reason(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    page.secrets.presence_error = SecretStoreUnavailable("the keychain is locked")
    resp = await page.client.get("/mcp")
    assert _server(resp.json(), "arch")["secret_reasons"] == {"Authorization": "the keychain is locked"}


async def test_get_mcp_warns_over_twenty_tools(page):
    _seed(page.store, _remote("big"), [_tool(f"t{i}") for i in range(21)])
    view = (await page.client.get("/mcp")).json()
    assert view["tools_on"] == 21 and view["warn"] is True and view["warning"] == TOOL_COUNT_WARNING


async def test_unreadable_record_is_503(page):
    page.db.parent.mkdir(parents=True, exist_ok=True)
    page.db.write_bytes(b"this is not a database" * 100)
    resp = await page.client.get("/mcp")
    assert resp.status_code == 503
    assert isinstance(resp.json()["detail"], str)


# ---- add: plan and save -----------------------------------------------------------------


async def test_plan_saves_nothing(page):
    text = _paste({"arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": f"Bearer {MARKER}"}}})
    resp = await page.client.post("/mcp/plan", json={"text": text})
    assert resp.status_code == 200
    body = resp.json()
    assert body["problems"] == []
    (planned,) = body["servers"]
    assert planned["name"] == "arch" and planned["secret_names"] == ["Authorization"]
    assert planned["runs"] == "This connects to http://127.0.0.1:9/mcp"
    assert MARKER not in resp.text
    assert page.store.servers() == {}
    assert page.secrets.values == {}


async def test_plan_local_shows_the_command_line(page):
    text = _paste({"notes": {"command": "uvx", "args": ["notes-server", "--dir", "/tmp/n"]}})
    body = (await page.client.post("/mcp/plan", json={"text": text})).json()
    assert body["servers"][0]["runs"] == "This runs `uvx notes-server --dir /tmp/n` on this machine as you"


async def test_plan_flags_a_replace(page):
    _seed(page.store, _remote("arch"))
    body = (await page.client.post("/mcp/plan", json={"text": _paste({"arch": {"url": "http://127.0.0.1:9/new"}})})).json()
    assert body["servers"][0]["replaces"] is True


async def test_plan_bad_json_is_422(page):
    resp = await page.client.post("/mcp/plan", json={"text": "{not json"})
    assert resp.status_code == 422
    assert resp.json()["detail"].startswith("not valid JSON")


async def test_save_requires_confirm(page):
    text = _paste({"arch": {"url": "http://127.0.0.1:9/mcp"}})
    missing = await page.client.post("/mcp/servers", json={"text": text, "replaces": []})
    false = await page.client.post("/mcp/servers", json={"text": text, "confirm": False, "replaces": []})
    assert missing.status_code == 422 and false.status_code == 422
    assert isinstance(missing.json()["detail"], str)
    assert page.store.servers() == {}


async def test_save_refuses_when_replaces_changed(page):
    text = _paste({"arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": MARKER}}})
    plan = (await page.client.post("/mcp/plan", json={"text": text})).json()
    assert plan["servers"][0]["replaces"] is False
    page.other.put_server(_remote("arch"))  # the CLI or another tab adds it in between
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": []})
    assert resp.status_code == 409
    assert resp.json() == {"detail": "the servers changed since the preview — preview again"}
    assert page.store.servers()["arch"].url == "http://127.0.0.1:9/arch"  # nothing saved
    assert page.secrets.values == {}

    # The other way round: the preview said "replaces", but the server has gone since.
    page.other.remove_server("arch")
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": ["arch"]})
    assert resp.status_code == 409
    assert page.store.servers() == {}


async def test_save_refuses_name_problems(page):
    _seed(page.store, _remote("a b"))
    text = _paste({"a_b": {"url": "http://127.0.0.1:9/mcp"}})
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": []})
    assert resp.status_code == 422
    assert "collides" in resp.json()["detail"]
    assert "a_b" not in page.store.servers()


async def test_save_remote_lists_tools(page):
    page.fakes.remote_tools["arch"] = [_tool("find"), _tool("get")]
    text = _paste({"arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": f"Bearer {MARKER}"}}})
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": []})
    assert resp.status_code == 200
    body = resp.json()
    server = _server(body["view"], "arch")
    assert [t["zname"] for t in server["tools"]] == ["arch__find", "arch__get"]
    assert all(t["trust"] == "asks" for t in server["tools"])
    assert server["secrets"] == {"Authorization": "set"}
    assert body["listing"][0].startswith("arch: added — 2 tools listed")
    assert body["notes"] == []
    assert page.fakes.headers_seen[0] == {"Authorization": f"Bearer {MARKER}"}
    assert page.secrets.values == {"mcp:arch:header:Authorization": f"Bearer {MARKER}"}
    assert MARKER not in resp.text


async def test_save_replace_with_matching_preview(page):
    _seed(page.store, _remote("arch", header_names=["Old"]))
    page.secrets.values["mcp:arch:header:Old"] = "x"
    page.fakes.remote_tools["arch"] = [_tool("find")]
    text = _paste({"arch": {"url": "http://127.0.0.1:9/new"}})
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": ["arch"]})
    assert resp.status_code == 200
    assert page.store.servers()["arch"].url == "http://127.0.0.1:9/new"
    assert page.secrets.values == {}  # the dropped header's secret is deleted


async def test_save_local_starts_it(page):
    page.fakes.local_tools["notes"] = [_tool("write")]
    text = _paste({"notes": {"command": "fake-server", "env": {"KEY": MARKER}}})
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": []})
    assert resp.status_code == 200
    body = resp.json()
    assert body["listing"] == ["notes: added — starting it now; Refresh lists its tools"]
    assert page.fakes.locals and page.fakes.locals[0].env == {"KEY": MARKER}  # started by sync_now
    assert MARKER not in resp.text


async def test_save_secret_store_unavailable_is_503(page):
    page.secrets.status = lambda: SimpleNamespace(available=False, why_unavailable="no secret store here")
    text = _paste({"arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": MARKER}}})
    resp = await page.client.post("/mcp/servers", json={"text": text, "confirm": True, "replaces": []})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "its secrets can't be stored: no secret store here"
    assert page.store.servers() == {}
    assert MARKER not in resp.text


# ---- per-server and per-tool actions ----------------------------------------------------


async def test_delete_server(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]), [_tool("find")])
    page.secrets.values["mcp:arch:header:Authorization"] = MARKER
    resp = await page.client.delete("/mcp/servers/arch")
    assert resp.status_code == 200
    assert resp.json() == {"view": resp.json()["view"], "notes": []}
    assert resp.json()["view"]["servers"] == []
    assert page.store.servers() == {} and page.secrets.values == {}


async def test_server_off_and_on(page):
    _seed(page.store, _remote("arch"), [_tool("find")])
    off = await page.client.put("/mcp/servers/arch/off")
    assert off.status_code == 200
    assert _server(off.json(), "arch")["on"] is False
    assert "server:arch" in page.store.off()
    on = await page.client.put("/mcp/servers/arch/on")
    assert _server(on.json(), "arch")["on"] is True
    assert "server:arch" not in page.store.off()


async def test_server_trust_and_untrust(page):
    _seed(page.store, _remote("arch"), [_tool("find"), _tool("get")])
    put = await page.client.put("/mcp/servers/arch/trust")
    assert put.status_code == 200
    server = _server(put.json(), "arch")
    assert server["trusted_server"] is True and {t["trust"] for t in server["tools"]} == {"trusted"}
    gone = await page.client.delete("/mcp/servers/arch/trust")
    assert gone.status_code == 200
    server = _server(gone.json(), "arch")
    assert server["trusted_server"] is False and {t["trust"] for t in server["tools"]} == {"asks"}


async def test_server_trust_with_no_tools_seen_404(page):
    _seed(page.store, _local("notes"))
    resp = await page.client.put("/mcp/servers/notes/trust")
    assert resp.status_code == 404
    assert resp.json()["detail"].startswith("no tools seen on notes yet")


async def test_tool_off_and_on(page):
    _seed(page.store, _remote("arch"), [_tool("find"), _tool("get")])
    off = await page.client.put("/mcp/tools/arch__find/off")
    assert off.status_code == 200
    tools = {t["zname"]: t["on"] for t in _server(off.json(), "arch")["tools"]}
    assert tools == {"arch__find": False, "arch__get": True}
    assert off.json()["tools_on"] == 1
    on = await page.client.put("/mcp/tools/arch__find/on")
    assert on.json()["tools_on"] == 2


async def test_tool_trust_and_untrust(page):
    _seed(page.store, _remote("arch"), [_tool("find"), _tool("get")])
    put = await page.client.put("/mcp/tools/arch__find/trust")
    assert put.status_code == 200
    trust = {t["zname"]: t["trust"] for t in _server(put.json(), "arch")["tools"]}
    assert trust == {"arch__find": "trusted", "arch__get": "asks"}
    assert "arch__find" in page.store.trust_entries()
    gone = await page.client.delete("/mcp/tools/arch__find/trust")
    assert gone.status_code == 200
    assert page.store.trust_entries() == {}


async def test_secret_put_never_echoes(page, caplog):
    caplog.set_level(logging.DEBUG)
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    resp = await page.client.put("/mcp/servers/arch/secrets/Authorization", json={"value": f"Bearer {MARKER}"})
    assert resp.status_code == 200
    assert _server(resp.json(), "arch")["secrets"] == {"Authorization": "set"}
    assert page.secrets.values == {"mcp:arch:header:Authorization": f"Bearer {MARKER}"}
    assert MARKER not in resp.text and MARKER not in caplog.text


async def test_secret_put_unknown_secret_404(page):
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    resp = await page.client.put("/mcp/servers/arch/secrets/Nope", json={"value": MARKER})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "no secret Nope on arch"}
    assert page.secrets.values == {}


async def test_secret_put_restarts_a_local_server(page):
    page.fakes.local_tools["notes"] = [_tool("write")]
    _seed(page.store, _local("notes", env_names=["KEY"]))
    page.secrets.values["mcp:notes:env:KEY"] = "old"
    page.sup.sync_now()
    await _until(lambda: page.fakes.locals and page.fakes.locals[-1].status == "running")
    first = page.fakes.locals[-1]
    resp = await page.client.put("/mcp/servers/notes/secrets/KEY", json={"value": "new"})
    assert resp.status_code == 200
    await _until(lambda: len(page.fakes.locals) == 2)
    assert first.stop_calls >= 1
    assert page.fakes.locals[-1].env == {"KEY": "new"}


async def test_timeout_put(page):
    _seed(page.store, _local("notes"))
    _seed(page.store, _remote("arch"), [_tool("find")])
    page.store.trust_tool(manage.trust_entry("arch", _tool("find"), "tool"))
    local = await page.client.put("/mcp/servers/notes/timeout", json={"timeout_s": 30})
    assert local.status_code == 200
    assert local.json()["notes"] == ["applies now; the server restarts"]
    assert _server(local.json()["view"], "notes")["timeout_s"] == 30.0
    remote = await page.client.put("/mcp/servers/arch/timeout", json={"timeout_s": 12.5})
    assert remote.json()["notes"] == []
    assert page.store.servers()["arch"].timeout_s == 12.5
    assert "arch__find" in page.store.trust_entries()  # trust is kept


async def test_timeout_validation_422(page):
    _seed(page.store, _remote("arch"))
    for body in ({"timeout_s": 0}, {"timeout_s": -1}, {"timeout_s": 601}, {"timeout_s": "30"},
                 {"timeout_s": True}, {"timeout_s": None}, {}):
        resp = await page.client.put("/mcp/servers/arch/timeout", json=body)
        assert resp.status_code == 422, body
        assert isinstance(resp.json()["detail"], str)
    assert page.store.servers()["arch"].timeout_s == 120.0


async def test_refresh_lists_servers_again(page):
    _seed(page.store, _remote("arch"))
    page.fakes.remote_tools["arch"] = [_tool("find")]
    resp = await page.client.post("/mcp/refresh")
    assert resp.status_code == 200
    assert [t["zname"] for t in _server(resp.json(), "arch")["tools"]] == ["arch__find"]


async def test_actions_on_missing_server_404(page):
    _seed(page.store, _remote("other"), [_tool("find")])
    calls = [
        ("DELETE", "/mcp/servers/gone", None),
        ("PUT", "/mcp/servers/gone/on", None),
        ("PUT", "/mcp/servers/gone/off", None),
        ("PUT", "/mcp/servers/gone/trust", None),
        ("DELETE", "/mcp/servers/gone/trust", None),
        ("PUT", "/mcp/servers/gone/secrets/KEY", {"value": MARKER}),
        ("PUT", "/mcp/servers/gone/timeout", {"timeout_s": 10}),
    ]
    for method, url, body in calls:
        resp = await page.client.request(method, url, json=body)
        assert resp.status_code == 404, (method, url)
        assert resp.json() == {"detail": "no server gone"}, (method, url)
    for method, url in (("PUT", "on"), ("PUT", "off"), ("PUT", "trust"), ("DELETE", "trust")):
        resp = await page.client.request(method, f"/mcp/tools/gone__find/{url}")
        assert resp.status_code == 404
        assert resp.json() == {"detail": "no tool gone__find"}
    assert set(page.store.servers()) == {"other"}


async def test_server_routes_handle_slash_and_space_in_name(page):
    names = ["team/a b", "team", "50%off", "x/on"]
    for name in names:
        _seed(page.store, _remote(name), [_tool("find")])
    target = "team/a b"
    path = _path(target)
    assert (await page.client.put(f"{path}/off")).status_code == 200
    assert page.store.off() == {f"server:{target}"}
    assert (await page.client.put(f"{path}/on")).status_code == 200
    assert (await page.client.put(f"{path}/trust")).status_code == 200
    assert page.store.trusted_servers() == {target}
    assert (await page.client.delete(f"{path}/trust")).status_code == 200
    assert (await page.client.put(f"{path}/timeout", json={"timeout_s": 9})).status_code == 200
    assert {n: s.timeout_s for n, s in page.store.servers().items()}[target] == 9.0
    assert all(s.timeout_s == 120.0 for n, s in page.store.servers().items() if n != target)
    for name in ("50%off", "x/on"):
        resp = await page.client.put(f"{_path(name)}/off")
        assert resp.status_code == 200, name
        assert _server(resp.json(), name)["on"] is False
    resp = await page.client.delete(path)
    assert resp.status_code == 200
    assert set(page.store.servers()) == {"team", "50%off", "x/on"}


# ---- inputs never echoed; origin --------------------------------------------------------


async def test_bad_bodies_never_echo_values(page, caplog):
    caplog.set_level(logging.DEBUG)
    _seed(page.store, _remote("arch", header_names=["Authorization"]))
    big = _paste({"arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": MARKER * 6000}}})
    requests = [
        ("PUT", "/mcp/servers/arch/secrets/Authorization", {"json": {"value": 123, "other": MARKER}}),
        ("PUT", "/mcp/servers/arch/secrets/Authorization", {"json": {"valu": MARKER}}),
        ("PUT", "/mcp/servers/arch/secrets/Authorization", {"content": f'{{"value": "{MARKER}"', "headers": {"content-type": "application/json"}}),
        ("POST", "/mcp/plan", {"json": {"text": f'{{"arch": {{"url": "{MARKER}",}}'}}),
        ("POST", "/mcp/plan", {"json": {"text": [MARKER]}}),
        ("POST", "/mcp/servers", {"json": {"text": f'{{"{MARKER}": ', "confirm": True, "replaces": []}}),
        ("POST", "/mcp/servers", {"json": {"text": MARKER, "confirm": MARKER, "replaces": []}}),
        ("PUT", "/mcp/servers/arch/timeout", {"json": {"timeout_s": MARKER}}),
        ("POST", "/mcp/plan", {"json": {"text": big}}),
        ("POST", "/mcp/servers", {"json": {"text": big, "confirm": True, "replaces": []}}),
    ]
    for method, url, kwargs in requests:
        resp = await page.client.request(method, url, **kwargs)
        assert resp.status_code in (413, 422), (method, url, resp.status_code)
        assert isinstance(resp.json()["detail"], str), (method, url)
        assert MARKER not in resp.text, (method, url)
    assert MARKER not in caplog.text
    assert page.secrets.values == {}
    assert (await page.client.post("/mcp/plan", json={"text": big})).status_code == 413


async def test_other_routes_keep_the_default_422(page):
    resp = await page.client.put("/preferences", json={"user_name": "x" * 65})
    assert resp.status_code == 422
    assert isinstance(resp.json()["detail"], list)


async def test_writes_refused_from_foreign_origin(page):
    _seed(page.store, _remote("arch"), [_tool("find")])
    evil = {"Origin": "https://evil.example"}
    calls = [
        ("POST", "/mcp/plan", {"text": "{}"}),
        ("POST", "/mcp/servers", {"text": "{}", "confirm": True, "replaces": []}),
        ("DELETE", "/mcp/servers/arch", None),
        ("PUT", "/mcp/servers/arch/off", None),
        ("PUT", "/mcp/tools/arch__find/trust", None),
        ("PUT", "/mcp/servers/arch/secrets/KEY", {"value": "x"}),
        ("PUT", "/mcp/servers/arch/timeout", {"timeout_s": 5}),
        ("POST", "/mcp/refresh", None),
    ]
    for method, url, body in calls:
        resp = await page.client.request(method, url, json=body, headers=evil)
        assert resp.status_code == 403, (method, url)
    assert page.store.off() == set() and page.store.trust_entries() == {}
    assert set(page.store.servers()) == {"arch"}


# ---- the page and the CLI agree -----------------------------------------------------------


async def test_page_and_cli_agree(page):
    _seed(page.store, _remote("arch"), [_tool("find"), _tool("get")])
    _seed(page.store, _remote("notes"), [_tool("write")])
    assert (await page.client.put("/mcp/tools/arch__find/trust")).status_code == 200
    assert (await page.client.put("/mcp/servers/notes/off")).status_code == 200
    args = argparse.Namespace(mcp_command="list")
    out = io.StringIO()
    code = run_mcp(args, load_config(page.cfg), out=out, secrets=page.secrets)
    assert code == 0
    text = out.getvalue()
    assert "arch (on)" in text and "notes (off)" in text
    assert "find — on, trusted" in text and "get — on, not trusted" in text


async def _until(cond, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)
