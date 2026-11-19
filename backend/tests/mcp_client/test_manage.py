from zygos.mcp.config import zygos_tool_name
from zygos.mcp.manage import trust_all, trust_entry, trust_one
from zygos.mcp.permission import seen_fingerprint
from zygos.mcp.store import SqliteMcpStore
from zygos.mcp.types import SeenTool


def _seen(name="find_tasks"):
    return SeenTool(name=name, description="d", input_schema={"type": "object"})


def test_trust_entry_pins_fingerprint():
    seen = _seen()
    entry = trust_entry("archon", seen, "tool")
    assert entry.fingerprint == seen_fingerprint(seen)
    assert entry.tool == zygos_tool_name("archon", "find_tasks")
    assert entry.via == "tool"


def test_trust_one_writes_tool_trust(tmp_path):
    store = SqliteMcpStore(tmp_path / "p.db")
    entry = trust_one(store, "archon", _seen())
    zname = zygos_tool_name("archon", "find_tasks")
    assert entry.tool == zname
    assert store.trust_entries()[zname].via == "tool"
    assert "archon" not in store.trusted_servers()


def test_trust_all_writes_server_trust(tmp_path):
    store = SqliteMcpStore(tmp_path / "p.db")
    tools = [_seen("a"), _seen("b")]
    entries = trust_all(store, "archon", tools)
    assert len(entries) == 2
    assert "archon" in store.trusted_servers()
    for t in tools:
        assert store.trust_entries()[zygos_tool_name("archon", t.name)].via == "server"
