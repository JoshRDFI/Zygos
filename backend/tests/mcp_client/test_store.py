import logging
import sqlite3
import threading
import time
from contextlib import closing

import pytest

from zygos.mcp.store import (
    McpStoreUnavailable,
    ServerState,
    SqliteMcpStore,
    TrustEntry,
    fingerprint,
)
from zygos.mcp.types import SeenTool, ServerSpec


def _spec(name="fs"):
    return ServerSpec(name=name, transport="stdio", command="x", env_names=["K"])


def _entry(tool="fs__read", via="tool", server=None):
    return TrustEntry(
        server=server or tool.split("__")[0], tool=tool, fingerprint="f",
        description="d", input_schema={}, via=via,
    )


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
    s.set_off("tool", "fs__read", True, server="fs")
    s.set_off("tool", "other__x", True, server="other")
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
    s.set_off("tool", "fs__a", True, server="fs")
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
            for i in range(20):
                a.put_state("fs", ServerState(status="running", detail=str(i)))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    def run_b():
        try:
            for i in range(20):
                b.trust_tool(_entry(f"fs__t{i}"))
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    ts = [threading.Thread(target=run_a), threading.Thread(target=run_b)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert a.state("fs").detail == "19"
    assert len(b.trust_entries()) == 20
    assert a.version() == 41


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


def test_put_server_rejects_double_underscore(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    with pytest.raises(ValueError, match="__"):
        s.put_server(_spec("a__b"))
    with pytest.raises(ValueError, match="__"):
        s.put_server(_spec("a_.b"))  # cleans to a__b


def test_remove_server_leaves_prefix_sibling_alone(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec("a"))
    s.put_server(_spec("ab"))
    s.trust_tool(_entry("a__x"))
    s.trust_tool(_entry("ab__x"))
    s.set_off("tool", "ab__x", True, server="ab")
    s.remove_server("a")
    assert set(s.servers()) == {"ab"}
    assert set(s.trust_entries()) == {"ab__x"}
    assert s.off() == {"tool:ab__x"}


def test_invalid_row_warning_has_no_stored_values(tmp_path, caplog):
    import sqlite3

    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec())
    con = sqlite3.connect(tmp_path / "p.db")
    con.execute("UPDATE mcp_servers SET spec = ?", ('{"name": "SECRETVALUE", "transport": "bogus"}',))
    con.commit()
    con.close()
    with caplog.at_level(logging.WARNING):
        assert s.servers() == {}
    assert "SECRETVALUE" not in caplog.text and "bogus" not in caplog.text
    assert "mcp_servers" in caplog.text


def test_set_off_tool_requires_server(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    with pytest.raises(ValueError, match="server"):
        s.set_off("tool", "fs__a", True)


@pytest.mark.parametrize("tool_a_, tool_a", [("x", "x"), ("y", "_x")])
def test_underscore_neighbour_server_untouched(tmp_path, tool_a_, tool_a):
    # server "a" tool "_x" -> a___x; server "a_" tool "x" -> a___x as well (a prefix match would catch it)
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec("a"))
    s.put_server(_spec("a_"))
    n_a, n_b = f"a__{tool_a}", f"a___{tool_a_}"
    s.trust_tool(_entry(n_a, "tool", server="a"))
    s.trust_server("a_", [_entry(n_b, "server", server="a_")])
    s.set_off("tool", n_b, True, server="a_")
    s.set_off("server", "a_", True)
    s.remove_server("a")
    assert set(s.servers()) == {"a_"}
    assert set(s.trust_entries()) == {n_b}
    assert s.trusted_servers() == {"a_"}
    assert s.off() == {f"tool:{n_b}", "server:a_"}
    s.trust_tool(_entry(n_a, "server", server="a"))
    s.untrust_server("a")
    assert set(s.trust_entries()) == {n_b}
    s.untrust_server("a_")
    assert s.trust_entries() == {}


def test_put_state_needs_its_server(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec())
    s.put_state("fs", ServerState(status="running", detail="old"))
    s.remove_server("fs")
    s.put_state("fs", ServerState(status="running", detail="late write"))  # e.g. a queued supervisor write
    s.put_state("never", ServerState(status="running"))
    with closing(sqlite3.connect(tmp_path / "p.db")) as con:
        assert con.execute("SELECT name FROM mcp_state").fetchall() == []
    s.put_server(_spec())
    assert s.state("fs") == ServerState()


def test_strict_reader_raises_instead_of_reading_empty(tmp_path):
    p = tmp_path / "p.db"
    p.write_bytes(b"not a database at all" * 100)
    reader = SqliteMcpStore(p).strict_reader(busy_timeout_s=0.2)
    with pytest.raises(McpStoreUnavailable):
        reader.servers()
    with pytest.raises(McpStoreUnavailable):
        reader.version()
    assert SqliteMcpStore(p).servers() == {}  # the CLI-facing store still reads empty
    assert SqliteMcpStore(tmp_path / "absent.db").strict_reader(busy_timeout_s=0.2).servers() == {}


def test_strict_reader_gives_up_fast_while_locked(tmp_path):
    p = tmp_path / "p.db"
    store = SqliteMcpStore(p)
    store.put_server(_spec())
    reader = store.strict_reader(busy_timeout_s=0.2)
    with closing(sqlite3.connect(p, isolation_level=None)) as con:
        con.execute("BEGIN EXCLUSIVE")
        t0 = time.monotonic()
        with pytest.raises(McpStoreUnavailable):
            reader.version()
        assert time.monotonic() - t0 < 0.5
        con.execute("ROLLBACK")
    assert set(reader.servers()) == {"fs"}


def test_replace_server_is_one_transaction_and_clears(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    s.put_server(_spec())
    s.put_state("fs", ServerState(status="running"))
    s.set_off("tool", "fs__x", True, server="fs")
    s.set_off("server", "fs", True)
    s.trust_server("fs", [])
    before = s.version()
    new = _spec().model_copy(update={"args": ["--other"]})
    s.replace_server(new)
    assert s.version() == before + 1  # one write
    assert s.servers() == {"fs": new}
    assert s.state("fs") == ServerState()
    assert s.off() == set() and s.trusted_servers() == set()
    with pytest.raises(ValueError):
        s.replace_server(_spec("a__b"))


def test_put_state_with_spec_skips_a_replaced_server(tmp_path):
    s = SqliteMcpStore(tmp_path / "p.db")
    old = _spec()
    s.put_server(old)
    new = old.model_copy(update={"args": ["--new"]})
    s.replace_server(new)
    s.put_state("fs", ServerState(status="running", detail="late, old spec"), spec=old)
    assert s.state("fs") == ServerState()
    s.put_state("fs", ServerState(status="running", detail="current"), spec=new)
    assert s.state("fs").detail == "current"
