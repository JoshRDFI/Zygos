from zygos.cli.__main__ import render_manifest
from zygos.runtime.manifest import McpServerManifest, McpToolManifest, runtime_manifest
from zygos.runtime.bootstrap import build_runtime
import asyncio


def test_inspect_shows_mcp_servers():
    runtime = build_runtime()
    try:
        m = runtime_manifest(runtime)
    finally:
        asyncio.run(runtime.aclose())
    m = m.model_copy(update={"mcp_servers": (McpServerManifest(
        name="archon", transport="http", address="http://x/mcp", enabled=True,
        status="reachable", era="2025-06-18",
        tools=(McpToolManifest(name="archon__a", server_tool="a", enabled=True, trust="trusted"),
               McpToolManifest(name="archon__b", server_tool="b", enabled=False, trust="not_trusted")),
    ),)})
    text = render_manifest(m)
    assert "mcp servers:" in text
    assert "archon" in text and "http://x/mcp" in text and "reachable" in text
    assert "2025-06-18" in text and "1/2 on" in text and "1 trusted" in text
