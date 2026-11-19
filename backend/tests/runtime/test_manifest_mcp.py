"""Manifest MCP section: servers and their tools with trust state, read from the store.
No secrets, no env/header values, nothing from ``ServerSpec.extra``."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
from fastapi import FastAPI

from zygos.api.routes_runtime import router
from zygos.mcp.permission import seen_fingerprint
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.manifest import runtime_manifest

SECRET = "hunter2-SECRET-VALUE"


def _config(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / ".zygos" / "p.db"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    return cfg, db


def _tool(name: str) -> SeenTool:
    return SeenTool(name=name, description=f"{name} things.", input_schema={"type": "object", "properties": {}})


def _seed(db: Path) -> None:
    store = SqliteMcpStore(db)
    store.put_server(ServerSpec(
        name="archon", transport="http", url="http://127.0.0.1:8051/mcp",
        header_names=["Authorization"], extra={"note": SECRET},
    ))
    store.put_server(ServerSpec(
        name="files", transport="stdio", command="npx", args=["-y", "server files", "/tmp"],
        env_names=["API_KEY"], extra={"x": SECRET},
    ))
    find, get = _tool("find_tasks"), _tool("get_task")
    now = time.time()
    store.put_state("archon", ServerState(
        status="reachable", era="2025-06-18", tools=[find, get], listed_at=now, expires_at=now + 300,
    ))
    store.put_state("files", ServerState(status="running", tools=[_tool("read")]))
    store.trust_tool(TrustEntry(
        server="archon", tool="archon__find_tasks", fingerprint=seen_fingerprint(find),
        description=find.description, input_schema=find.input_schema, via="tool",
    ))
    changed = _tool("read").model_copy(update={"description": "old text"})
    store.trust_tool(TrustEntry(
        server="files", tool="files__read", fingerprint=seen_fingerprint(changed),
        description=changed.description, input_schema=changed.input_schema, via="tool",
    ))
    store.set_off("tool", "archon__get_task", True, server="archon")
    store.set_off("server", "files", True)


async def test_manifest_lists_mcp_without_secrets(tmp_path):
    cfg, db = _config(tmp_path)
    _seed(db)
    runtime = build_runtime(cfg)
    try:
        manifest = runtime_manifest(runtime)
    finally:
        await runtime.aclose()
    servers = {s.name: s.model_dump(mode="json") for s in manifest.mcp_servers}
    assert servers == {
        "archon": {
            "name": "archon", "transport": "http", "address": "http://127.0.0.1:8051/mcp",
            "enabled": True, "status": "reachable", "era": "2025-06-18",
            "tools": [
                {"name": "archon__find_tasks", "server_tool": "find_tasks", "enabled": True, "trust": "trusted"},
                {"name": "archon__get_task", "server_tool": "get_task", "enabled": False, "trust": "not_trusted"},
            ],
        },
        "files": {
            "name": "files", "transport": "stdio", "address": "npx -y 'server files' /tmp",
            "enabled": False, "status": "running", "era": None,
            "tools": [{"name": "files__read", "server_tool": "read", "enabled": True, "trust": "changed"}],
        },
    }
    dumped = manifest.model_dump_json()
    assert SECRET not in dumped
    assert "Authorization" not in dumped and "API_KEY" not in dumped


async def test_manifest_mcp_empty_when_no_servers(tmp_path):
    cfg, db = _config(tmp_path)
    runtime = build_runtime(cfg)
    try:
        assert runtime_manifest(runtime).mcp_servers == ()
    finally:
        await runtime.aclose()
    assert not db.exists()  # the manifest never creates the database


async def test_get_runtime_route_carries_mcp(tmp_path):
    cfg, db = _config(tmp_path)
    _seed(db)
    runtime = build_runtime(cfg)
    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            body = (await client.get("/runtime")).json()
    finally:
        await runtime.aclose()
    assert [s["name"] for s in body["mcp_servers"]] == ["archon", "files"]
    assert SECRET not in str(body)
