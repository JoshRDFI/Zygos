"""Live check against the local Archon MCP server (read-only). Excluded by default."""

from __future__ import annotations

import dataclasses

import httpx
import pytest

pytest.importorskip("mcp")

from zygos.api.app import create_app  # noqa: E402
from zygos.mcp.remote import call_remote, list_remote  # noqa: E402
from zygos.mcp.store import SqliteMcpStore  # noqa: E402
from zygos.mcp.supervisor import McpSupervisor  # noqa: E402
from zygos.mcp.types import ServerSpec  # noqa: E402
from zygos.runtime.bootstrap import build_runtime  # noqa: E402

pytestmark = pytest.mark.live_mcp

SPEC = ServerSpec(name="archon", transport="http", url="http://localhost:8051/mcp", timeout_s=20.0)


async def test_list_and_call_health_check():
    result = await list_remote(SPEC, {}, era=None, discover=None)
    print(f"era={result.era} tools={len(result.tools)}")
    assert result.era and result.era.startswith("20")  # a dated handshake-era protocol
    assert len(result.tools) >= 1
    assert "health_check" in {t.name for t in result.tools}
    reply = await call_remote(SPEC, {}, "health_check", {}, era=result.era, discover=result.discover)
    print(f"health_check -> {reply!r}"[:300])
    assert reply is not None


async def test_mcp_route_lists_archon_tools(tmp_path):
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
    store = SqliteMcpStore(db)
    store.put_server(SPEC)
    sup = McpSupervisor(store, runtime.secrets, runtime.tool_service, rules=[], new_context=runtime.new_context)
    app = create_app(dataclasses.replace(runtime, mcp=sup))
    await sup.start()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost")
    try:
        resp = await client.post("/mcp/refresh")
        assert resp.status_code == 200
        view = (await client.get("/mcp")).json()
        server = next(s for s in view["servers"] if s["name"] == "archon")
        names = {t["server_tool"] for t in server["tools"]}
        print(f"status={server['status']} tools={len(names)}")
        assert "health_check" in names
        assert all(t["zname"].startswith("archon__") for t in server["tools"])
    finally:
        await client.aclose()
        await app.state.runtime.aclose()
        await sup.aclose()
        await built_mcp.aclose()
