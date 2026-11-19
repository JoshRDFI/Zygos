"""Live check against the local Archon MCP server (read-only). Excluded by default."""

from __future__ import annotations

import pytest

pytest.importorskip("mcp")

from zygos.mcp.remote import call_remote, list_remote  # noqa: E402
from zygos.mcp.types import ServerSpec  # noqa: E402

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
