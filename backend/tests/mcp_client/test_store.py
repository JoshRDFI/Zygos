import threading

from zygos.mcp.store import (
    ServerState,
    SqliteMcpStore,
    TrustEntry,
    fingerprint,
)
from zygos.mcp.types import SeenTool, ServerSpec


def _spec(name="fs"):
    return ServerSpec(name=name, transport="stdio", command="x", env_names=["K"])


def _entry(tool="fs__read", via="tool"):
    return TrustEntry(tool=tool, fingerprint="f", description="d", input_schema={}, via=via)


def test_roundtrip_server_and_state(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec())
    assert s.servers() == {"fs": _spec()}
    st = ServerState(
        era="e", discover={"a": 1}, tools=[SeenTool(name="t", description="d", input_schema={})],
        listed_at=1.0, expires_at=2.0, status="running", detail="ok", exit_code=3,
        stderr_tail="err", status_at=5.0,
    )
    s.put_state("fs", st)
    assert s.state("fs") == st
    assert s.state("nope") == ServerState()


def test_remove_server_clears_everything(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec())
    s.put_server(_spec("other"))
    s.put_state("fs", ServerState(status="running"))
    s.trust_tool(_entry("fs__read"))
    s.trust_tool(_entry("other__x"))
    s.trust_server("fs", [_entry("fs__w", "server")])
    s.set_off("server", "fs", True)
    s.set_off("tool", "fs__read", True)
    s.set_off("tool", "other__x", True)
    s.remove_server("fs")
    assert set(s.servers()) == {"other"}
    assert s.state("fs") == ServerState()
    assert set(s.trust_entries()) == {"other__x"}
    assert s.trusted_servers() == set()
    assert s.off() == {"tool:other__x"}


def test_trust_tool_and_server(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.trust_tool(_entry("fs__a"))
    s.trust_server("fs", [_entry("fs__b", "server"), _entry("fs__c", "server")])
    assert set(s.trust_entries()) == {"fs__a", "fs__b", "fs__c"}
    assert s.trust_entries()["fs__b"].via == "server"
    assert s.trusted_servers() == {"fs"}
    s.untrust_tool("fs__a")
    assert "fs__a" not in s.trust_entries()


def test_untrust_server_keeps_tool_trust(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.trust_tool(_entry("fs__a", "tool"))
    s.trust_server("fs", [_entry("fs__b", "server")])
    s.untrust_server("fs")
    assert s.trusted_servers() == set()
    assert set(s.trust_entries()) == {"fs__a"}


def test_off_keys(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.set_off("server", "fs", True)
    s.set_off("tool", "fs__a", True)
    assert s.off() == {"server:fs", "tool:fs__a"}
    s.set_off("server", "fs", False)
    s.set_off("server", "never", False)
    assert s.off() == {"tool:fs__a"}


def test_reads_never_create_db(tmp_path):
    p = tmp_path / "p.db"
    s = SqliteMcpStore(p)
    assert s.servers() == {}
    assert s.state("a") == ServerState()
    assert s.trust_entries() == {}
    assert s.trusted_servers() == set()
    assert s.off() == set()
    assert s.version() == 0
    assert not p.exists()


def test_unreadable_db_reads_empty_with_warning(tmp_path, caplog):
    p = tmp_path / "p.db"
    p.write_bytes(b"not a database at all" * 100)
    s = SqliteMcpStore(p)
    with caplog.at_level("WARNING"):
        assert s.servers() == {}
        assert s.off() == set()
    assert "unreadable" in caplog.text


def test_concurrent_writers_lose_nothing(tmp_path):
    p = tmp_path / "p.db"
    a, b = SqliteMcpStore(p), SqliteMcpStore(p)
    a.put_server(_spec())
    errors = []

    def run_a():
        try:
            for i in range(50):
                a.put_state(f"s{i}", ServerState(status="running", detail=str(i)))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def run_b():
        try:
            for i in range(50):
                b.trust_tool(_entry(f"fs__t{i}"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=run_a), threading.Thread(target=run_b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert all(a.state(f"s{i}").detail == str(i) for i in range(50))
    assert len(b.trust_entries()) == 50
    assert a.version() == 101


def test_fingerprint_changes_with_description_or_schema():
    base = fingerprint("n", "d", {"a": 1})
    assert base == fingerprint("n", "d", {"a": 1})
    assert len(base) == 64
    assert base != fingerprint("n", "d2", {"a": 1})
    assert base != fingerprint("n", "d", {"a": 2})
    assert base != fingerprint("m", "d", {"a": 1})


def test_version_bumps_on_write(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    assert s.version() == 0
    s.put_server(_spec())
    v1 = s.version()
    s.set_off("server", "fs", True)
    v2 = s.version()
    s.remove_server("fs")
    assert 0 < v1 < v2 < s.version()
