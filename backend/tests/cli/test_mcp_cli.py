"""`zygos mcp add | list | remove | on | off | trust | untrust` (RFC-0015 phase 1a)."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest

from zygos.cli.__main__ import _build_parser, main
from zygos.cli.mcp import run_mcp
from zygos.config.loader import load_config
from zygos.mcp.permission import seen_fingerprint, trust_state
from zygos.mcp.store import SqliteMcpStore
from zygos.mcp.supervisor import NO_MCP, TOOL_COUNT_WARNING
from zygos.mcp.types import SeenTool
from zygos.mcp.wire import ListResult
from zygos.secrets import Presence, SecretStoreUnavailable, build_secret_store

pytest.importorskip("cryptography")

SECRET = "sk-123"


@pytest.fixture
def setup(tmp_path):
    db = tmp_path / ".zygos" / "preferences.db"
    path = tmp_path / "config.yaml"
    path.write_text(
        f"personalization:\n  db_path: '{db}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
        "secrets:\n  backend: encrypted_file\n"
    )
    return SimpleNamespace(path=path, db=db, config=load_config(path), tmp=tmp_path)


def _file(tmp_path, servers: dict, name: str = "servers.json") -> str:
    target = tmp_path / name
    target.write_text(json.dumps({"mcpServers": servers}))
    return str(target)


def _run(setup, *argv: str, answers=(), **kwargs):
    args = _build_parser().parse_args(["mcp", *argv])
    out = io.StringIO()
    pending = list(answers)

    def input_fn(prompt: str) -> str:
        out.write(prompt)
        if not pending:
            raise EOFError
        return pending.pop(0)

    code = run_mcp(args, setup.config, input_fn=input_fn, out=out, **kwargs)
    return code, out.getvalue()


def _tool(name: str, description: str = "", schema=None) -> SeenTool:
    return SeenTool(
        name=name,
        description=description or f"The {name} tool.",
        input_schema=schema or {"type": "object", "properties": {}},
    )


class ListSpy:
    """Stands in for ``list_remote``; records every contact."""

    def __init__(self, tools=None, *, era: str = "2025-06-18") -> None:
        self.calls: list[tuple[str, dict]] = []
        self.tools = tools if tools is not None else [_tool("echo")]
        self.era = era

    async def __call__(self, spec, headers, *, era, discover):
        self.calls.append((spec.name, dict(headers)))
        return ListResult(era=self.era, discover=None, tools=list(self.tools), ttl_s=None)


def _store(setup) -> SqliteMcpStore:
    return SqliteMcpStore(setup.db)


# ---- add ----------------------------------------------------------------------


def test_add_shows_command_and_confirms(setup):
    spy = ListSpy()
    path = _file(setup.tmp, {
        "files": {"command": "npx", "args": ["-y", "server-files", "/my dir"]},
        "remote": {"url": "http://127.0.0.1:9/mcp"},
    })
    code, out = _run(setup, "add", path, answers=["n"], list_remote=spy)
    assert code == 1
    assert "This runs `npx -y server-files '/my dir'` on this machine as you" in out
    assert "This connects to http://127.0.0.1:9/mcp" in out
    assert "Add these servers? [y/N]" in out
    assert "Nothing added." in out
    assert spy.calls == []
    assert _store(setup).servers() == {}
    assert not setup.db.exists()  # nothing written at all

    # EOF at the prompt is a "no" too.
    code, _ = _run(setup, "add", path, answers=[], list_remote=spy)
    assert code == 1 and spy.calls == [] and _store(setup).servers() == {}


def test_add_yes_stores_secrets_not_values(setup):
    path = _file(setup.tmp, {
        "search": {"command": "search-server", "env": {"SEARCH_API_KEY": SECRET}, "note": "sk-extra-999"},
    })
    code, out = _run(setup, "add", path, "--yes", list_remote=ListSpy())
    assert code == 0, out
    assert "secrets: SEARCH_API_KEY (stored in the secret store)" in out
    assert "its tools are listed when zygos serve starts it" in out
    assert "Add these servers?" not in out
    assert SECRET not in out and "sk-extra-999" not in out
    spec = _store(setup).servers()["search"]
    assert spec.env_names == ["SEARCH_API_KEY"]
    assert SECRET.encode() not in setup.db.read_bytes()
    assert build_secret_store(setup.config).get("mcp:search:env:SEARCH_API_KEY") == SECRET


class UnavailableSecrets:
    """A secret store that can't be used (no extra, no keychain)."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def status(self):
        return SimpleNamespace(available=False, why_unavailable="no secret store here: install .[secrets]")

    def set(self, handle, value):  # pragma: no cover - must never be reached
        raise AssertionError("set called on an unavailable store")

    def get(self, handle):
        raise SecretStoreUnavailable("no secret store here: install .[secrets]")

    def delete(self, handle):
        self.deleted.append(handle)
        raise SecretStoreUnavailable("no secret store here: install .[secrets]")

    def presence(self, handle):
        return Presence("unknown", "no secret store here: install .[secrets]")


def test_add_refused_when_secret_store_unavailable(setup):
    path = _file(setup.tmp, {
        "search": {"command": "search-server", "env": {"SEARCH_API_KEY": SECRET}},
        "plain": {"command": "plain-server"},
    })
    code, out = _run(setup, "add", path, "--yes", secrets=UnavailableSecrets(), list_remote=ListSpy())
    assert code == 1
    assert "search: not added" in out
    assert "no secret store here: install .[secrets]" in out
    assert SECRET not in out
    assert set(_store(setup).servers()) == {"plain"}


def test_add_remote_lists_tools(setup):
    pytest.importorskip("mcp")
    from tests.mcp_client.servers import BEARER_TOKEN, build_server, http_app, require_bearer, serve

    token = f"Bearer {BEARER_TOKEN}"
    with serve(require_bearer(http_app(build_server()))) as url:
        path = _file(setup.tmp, {"echo": {"url": url, "headers": {"Authorization": token}}})
        code, out = _run(setup, "add", path, "--yes", clock=lambda: 1000.0)
    assert code == 0, out
    assert "2 tools listed" in out
    assert "zygos mcp trust echo/TOOL (or echo for all 2)" in out
    assert BEARER_TOKEN not in out
    state = _store(setup).state("echo")
    assert state.status == "reachable"
    assert {t.name for t in state.tools} >= {"echo", "pic"}
    assert state.era and state.listed_at == 1000.0 and state.status_at == 1000.0
    assert state.expires_at == 1000.0 + 300.0
    assert BEARER_TOKEN.encode() not in setup.db.read_bytes()
    assert build_secret_store(setup.config).get("mcp:echo:header:Authorization") == token


def test_add_unreachable_remote_still_added(setup):
    pytest.importorskip("mcp")
    from tests.mcp_client.servers import closed_port

    url = f"http://127.0.0.1:{closed_port()}/mcp"
    path = _file(setup.tmp, {"gone": {"url": url, "timeout_s": 5}})
    code, out = _run(setup, "add", path, "--yes")
    assert code == 0, out
    assert "gone: added, but its tools couldn't be listed" in out
    assert "gone" in _store(setup).servers()
    state = _store(setup).state("gone")
    assert state.status == "unreachable" and state.detail
    assert state.tools == []


def test_add_remote_without_mcp_extra_saves_and_says_how(setup):
    spy = ListSpy()
    path = _file(setup.tmp, {"remote": {"url": "http://127.0.0.1:9/mcp"}})
    code, out = _run(setup, "add", path, "--yes", list_remote=spy, mcp_installed=lambda: False)
    assert code == 0
    assert "remote: added, but its tools couldn't be listed" in out
    assert NO_MCP in out
    assert spy.calls == []
    assert "remote" in _store(setup).servers()


def test_add_collision_refused(setup):
    path = _file(setup.tmp, {"a.b": {"command": "x"}, "a_b": {"command": "y"}})
    code, out = _run(setup, "add", path, "--yes")
    assert code == 1
    assert "both become 'a_b'" in out
    assert _store(setup).servers() == {}


def test_add_bad_json_refused(setup):
    bad = setup.tmp / "bad.json"
    bad.write_text("{nope")
    code, out = _run(setup, "add", str(bad), "--yes")
    assert code == 1 and "not valid JSON" in out


def test_replace_asks_and_clears_trust(setup):
    first = _file(setup.tmp, {
        "arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": SECRET, "X-Other": "v-2"}},
    }, "first.json")
    spy = ListSpy()
    assert _run(setup, "add", first, "--yes", list_remote=spy)[0] == 0
    assert spy.calls == [("arch", {"Authorization": SECRET, "X-Other": "v-2"})]
    assert _run(setup, "trust", "arch/echo")[0] == 0
    assert _run(setup, "off", "arch/echo")[0] == 0
    store = _store(setup)
    assert store.trust_entries() and store.off()

    second = _file(setup.tmp, {
        "arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "sk-456"}},
    }, "second.json")
    code, out = _run(setup, "add", second, answers=["n"], list_remote=spy)
    assert code == 1
    assert "replaces the existing server arch (its trust is cleared)" in out
    assert store.trust_entries() and store.off()  # declined: untouched

    code, out = _run(setup, "add", second, answers=["y"], list_remote=spy)
    assert code == 0, out
    assert store.trust_entries() == {} and store.off() == set()
    assert store.servers()["arch"].header_names == ["Authorization"]
    secrets = build_secret_store(setup.config)
    assert secrets.get("mcp:arch:header:Authorization") == "sk-456"
    assert secrets.get("mcp:arch:header:X-Other") is None  # no longer in the spec
    assert store.state("arch").status == "reachable"  # listed again for the new spec


# ---- list -----------------------------------------------------------------------


def test_list_presence_only_and_warning_over_20(setup):
    tools = [_tool(f"t{i}") for i in range(21)]
    path = _file(setup.tmp, {
        "big": {
            "url": "http://127.0.0.1:9/mcp",
            "headers": {"Authorization": SECRET, "X-Gone": "sk-gone"},
            "note": "sk-extra-999",
        },
    })
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy(tools), clock=lambda: 0.0)[0] == 0
    build_secret_store(setup.config).delete("mcp:big:header:X-Gone")
    code, out = _run(setup, "list")
    assert code == 0
    assert "big (on)" in out
    assert "This connects to http://127.0.0.1:9/mcp" in out
    assert "protocol 2025-06-18" in out
    assert "reachable (as of 1970-01-01" in out or "reachable (as of 1969-12-31" in out
    assert "Authorization = set" in out
    assert "X-Gone = not set" in out
    for leaked in (SECRET, "sk-gone", "sk-extra-999"):
        assert leaked not in out
    assert "t0 — on, not trusted" in out
    assert "21 tools on" in out
    assert TOOL_COUNT_WARNING in out
    assert NO_MCP not in out

    assert _run(setup, "off", "big/t0")[0] == 0
    code, out = _run(setup, "list")
    assert "t0 — off, not trusted" in out
    assert "20 tools on" in out and TOOL_COUNT_WARNING not in out


def test_list_shows_left_out_and_install_line(setup):
    bad = SeenTool(name="bad", description="Bad.", input_schema={"type": "string"})
    path = _file(setup.tmp, {"r": {"url": "http://127.0.0.1:9/mcp"}})
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy([_tool("ok"), bad]))[0] == 0
    code, out = _run(setup, "list", mcp_installed=lambda: False)
    assert code == 0
    assert "bad — left out:" in out
    assert "1 tool on" in out
    assert out.count(NO_MCP) == 1


def test_list_empty(setup):
    code, out = _run(setup, "list")
    assert code == 0 and "No MCP servers added" in out
    assert not setup.db.exists()


def test_list_with_unavailable_secret_store_still_works(setup):
    path = _file(setup.tmp, {"r": {"url": "http://127.0.0.1:9/mcp"}})
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy())[0] == 0
    store = _store(setup)
    spec = store.servers()["r"].model_copy(update={"header_names": ["Authorization"]})
    store.put_server(spec)
    code, out = _run(setup, "list", secrets=UnavailableSecrets())
    assert code == 0
    assert "Authorization = unknown (no secret store here" in out


# ---- trust / untrust ----------------------------------------------------------------


def test_trust_unseen_tool_errors(setup):
    path = _file(setup.tmp, {"loc": {"command": "local-server"}})
    assert _run(setup, "add", path, "--yes")[0] == 0
    code, out = _run(setup, "trust", "loc/read")
    assert code == 1
    assert "no tool read seen on loc yet — its tools are listed when zygos serve starts it" in out
    code, out = _run(setup, "trust", "loc")
    assert code == 1 and "seen on loc yet" in out
    code, out = _run(setup, "trust", "nobody/read")
    assert code == 1 and "no server nobody" in out

    remote = _file(setup.tmp, {"rem": {"url": "http://127.0.0.1:9/mcp"}}, "remote.json")
    assert _run(setup, "add", remote, "--yes", list_remote=ListSpy())[0] == 0
    code, out = _run(setup, "trust", "rem/nope")
    assert code == 1 and "no tool nope seen on rem yet" in out
    assert "zygos serve starts it" not in out
    assert _store(setup).trust_entries() == {}


def test_trust_then_change_shows_changed(setup):
    path = _file(setup.tmp, {"rem": {"url": "http://127.0.0.1:9/mcp"}})
    old = _tool("echo", "Echo the text back.")
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy([old, _tool("other")]))[0] == 0
    code, out = _run(setup, "trust", "rem/echo")
    assert code == 0, out
    store = _store(setup)
    entry = store.trust_entries()["rem__echo"]
    # Matches what the supervisor's gate checks.
    assert entry.server == "rem" and entry.via == "tool"
    assert entry.fingerprint == seen_fingerprint(old)
    assert trust_state("rem__echo", old, store.trust_entries()) == "trusted"
    _, out = _run(setup, "list")
    assert "echo — on, trusted" in out
    assert "other — on, not trusted" in out

    new = _tool("echo", "Echo the text and send it somewhere.")
    store.put_state("rem", store.state("rem").model_copy(update={"tools": [new, _tool("other")]}))
    _, out = _run(setup, "list")
    assert "echo — on, changed since you trusted it" in out
    assert "was: Echo the text back." in out
    assert "now: Echo the text and send it somewhere." in out

    # Trusting the server covers the tools seen now (the changed one too).
    assert _run(setup, "trust", "rem")[0] == 0
    entries = store.trust_entries()
    assert entries["rem__echo"].fingerprint == seen_fingerprint(new)
    assert entries["rem__other"].via == "server"
    assert "rem" in store.trusted_servers()

    assert _run(setup, "untrust", "rem")[0] == 0
    assert store.trusted_servers() == set() and store.trust_entries() == {}
    assert _run(setup, "trust", "rem/echo")[0] == 0
    assert _run(setup, "untrust", "rem/echo")[0] == 0
    assert store.trust_entries() == {}


# ---- remove, on/off -------------------------------------------------------------------


def test_remove_deletes_secrets(setup):
    path = _file(setup.tmp, {"search": {"command": "s", "env": {"KEY": SECRET}}})
    assert _run(setup, "add", path, "--yes")[0] == 0
    code, out = _run(setup, "remove", "search")
    assert code == 0, out
    assert _store(setup).servers() == {}
    assert build_secret_store(setup.config).get("mcp:search:env:KEY") is None
    code, out = _run(setup, "remove", "search")
    assert code == 1 and "no server search" in out


def test_remove_reports_undeletable_secrets(setup):
    path = _file(setup.tmp, {"search": {"command": "s", "env": {"KEY": SECRET}}})
    assert _run(setup, "add", path, "--yes")[0] == 0
    secrets = UnavailableSecrets()
    code, out = _run(setup, "remove", "search", secrets=secrets)
    assert code == 0
    assert _store(setup).servers() == {}
    assert secrets.deleted == ["mcp:search:env:KEY"]
    assert "could not delete the secret KEY" in out


def test_on_off_tool(setup):
    path = _file(setup.tmp, {"rem": {"url": "http://127.0.0.1:9/mcp"}})
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy())[0] == 0
    store = _store(setup)
    assert _run(setup, "off", "rem/echo")[0] == 0
    assert store.off() == {"tool:rem__echo"}
    assert _run(setup, "on", "rem/echo")[0] == 0
    assert store.off() == set()
    assert _run(setup, "off", "rem")[0] == 0
    assert store.off() == {"server:rem"}
    _, out = _run(setup, "list")
    assert "rem (off)" in out and "0 tools on" in out
    assert _run(setup, "on", "rem")[0] == 0
    assert store.off() == set()
    assert _run(setup, "off", "rem/missing")[0] == 1
    assert _run(setup, "off", "ghost")[0] == 1


# ---- wiring -----------------------------------------------------------------------------


def test_main_routes_mcp(setup, capsys):
    assert main(["--config", str(setup.path), "mcp", "list"]) == 0
    assert "No MCP servers added" in capsys.readouterr().out


# ---- fix round 1 -------------------------------------------------------------------------


def test_stdin_json_confirms_on_the_terminal(setup):
    spec = json.dumps({"mcpServers": {"loc": {"command": "local-server"}}})
    tty = io.StringIO("y\n")
    code, out = _run(setup, "add", stdin=io.StringIO(spec), tty_opener=lambda: tty)
    assert code == 0, out
    assert "Add these servers? [y/N]" in out
    assert "loc" in _store(setup).servers()

    code, out = _run(setup, "add", stdin=io.StringIO(spec.replace("loc", "two")),
                     tty_opener=lambda: io.StringIO("n\n"))
    assert code == 1 and "two" not in _store(setup).servers()


def test_stdin_json_without_terminal_needs_yes(setup):
    spec = json.dumps({"mcpServers": {"loc": {"command": "local-server"}}})
    stdin = io.StringIO(spec)
    code, out = _run(setup, "add", stdin=stdin, tty_opener=lambda: None)
    assert code == 1
    assert "stdin was used for the JSON — pass --yes or give a FILE" in out
    assert stdin.tell() == 0  # refused before reading
    assert _store(setup).servers() == {}
    code, out = _run(setup, "add", "--yes", stdin=io.StringIO(spec), tty_opener=lambda: None)
    assert code == 0 and "loc" in _store(setup).servers()


async def test_cli_trust_opens_the_supervisor_gate(setup):
    from zygos.mcp.supervisor import Connectors, McpSupervisor
    from zygos.runtime.context import root_context
    from zygos.runtime.events import InProcessEventBus
    from zygos.tools import ToolService

    import asyncio

    async def cli(*argv, **kwargs) -> int:  # the CLI is its own process: never on this loop
        return (await asyncio.to_thread(_run, setup, *argv, **kwargs))[0]

    spy = ListSpy([_tool("find"), _tool("get")])
    path = _file(setup.tmp, {"archon": {"url": "http://127.0.0.1:9/mcp"}})
    assert await cli("add", path, "--yes", list_remote=spy) == 0

    async def call_remote(*args, **kwargs):  # pragma: no cover - never called here
        raise AssertionError

    sup = McpSupervisor(
        SqliteMcpStore(setup.db), UnavailableSecrets(), ToolService(), rules=[],
        new_context=lambda: root_context(InProcessEventBus()),
        connectors=Connectors(local=None, list_remote=spy, call_remote=call_remote),  # type: ignore[arg-type]
    )
    try:
        def gate(name: str) -> str:
            tools = {t.meta.name: t.meta for t in sup.before_turn()}
            return sup.gate(tools[name])

        assert gate("archon__find") == "not_trusted"
        assert await cli("trust", "archon/find") == 0
        assert gate("archon__find") == "allow"
        assert gate("archon__get") == "not_trusted"
        assert await cli("untrust", "archon/find") == 0
        assert gate("archon__find") == "not_trusted"
        assert await cli("trust", "archon") == 0
        assert gate("archon__find") == "allow" and gate("archon__get") == "allow"
        assert await cli("untrust", "archon") == 0
        assert gate("archon__get") == "not_trusted"
    finally:
        await sup.aclose()


class FlakySecrets:
    """The real store, except ``set`` fails for some handles (or every set once ``broken``)."""

    def __init__(self, real, fail: set[str], *, stays_broken: bool = False) -> None:
        self.real, self.fail, self.stays_broken, self.broken = real, fail, stays_broken, False

    def __getattr__(self, name):
        return getattr(self.real, name)

    def set(self, handle, value):
        if handle in self.fail or self.broken:
            self.broken = self.stays_broken
            raise SecretStoreUnavailable("the keychain went away")
        self.real.set(handle, value)


def _replace_setup(setup):
    first = _file(setup.tmp, {
        "arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "sk-old", "X-Other": "v-2"}},
    }, "first.json")
    assert _run(setup, "add", first, "--yes", list_remote=ListSpy())[0] == 0
    assert _run(setup, "trust", "arch/echo")[0] == 0
    return _file(setup.tmp, {
        "arch": {"url": "http://127.0.0.1:9/mcp", "headers": {"Authorization": "sk-new", "X-Fail": "v-3"}},
    }, "second.json")


def test_replace_restores_secrets_when_a_set_fails(setup):
    second = _replace_setup(setup)
    real = build_secret_store(setup.config)
    flaky = FlakySecrets(real, {"mcp:arch:header:X-Fail"})
    code, out = _run(setup, "add", second, "--yes", secrets=flaky, list_remote=ListSpy())
    assert code == 1
    assert "arch: not added — its secrets can't be stored: the keychain went away" in out
    assert "restored" in out
    assert real.get("mcp:arch:header:Authorization") == "sk-old"
    assert real.get("mcp:arch:header:X-Fail") is None
    store = _store(setup)
    assert store.servers()["arch"].header_names == ["Authorization", "X-Other"]
    assert "arch__echo" in store.trust_entries()  # the old server is untouched
    assert "sk-old" not in out and "sk-new" not in out


def test_replace_says_which_secrets_were_overwritten_when_restore_fails(setup):
    second = _replace_setup(setup)
    real = build_secret_store(setup.config)
    flaky = FlakySecrets(real, {"mcp:arch:header:X-Fail"}, stays_broken=True)
    code, out = _run(setup, "add", second, "--yes", secrets=flaky, list_remote=ListSpy())
    assert code == 1
    assert "arch: the secret Authorization was overwritten and couldn't be restored" in out
    assert "sk-old" not in out and "sk-new" not in out


def test_add_listing_is_bounded(setup, monkeypatch):
    import asyncio

    import zygos.cli.mcp as cli_mcp

    monkeypatch.setattr(cli_mcp, "_ADD_LIST_CAP_S", 0.2)

    async def silent(spec, headers, *, era, discover):
        await asyncio.sleep(30)

    path = _file(setup.tmp, {"slow": {"url": "http://127.0.0.1:9/mcp"}})
    code, out = _run(setup, "add", path, "--yes", list_remote=silent)
    assert code == 0
    assert "slow: added, but its tools couldn't be listed: no answer within 0.2 s — zygos serve tries again" in out
    state = _store(setup).state("slow")
    assert state.status == "unreachable" and state.detail == "no answer within 0.2 s"


def test_target_picks_the_longest_server_prefix(setup):
    path = _file(setup.tmp, {
        "a": {"url": "http://127.0.0.1:9/a"},
        "a/b": {"url": "http://127.0.0.1:9/ab"},
    })
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy([_tool("x"), _tool("b/x")]))[0] == 0
    assert _run(setup, "trust", "a/b/x")[0] == 0
    assert set(_store(setup).trust_entries()) == {"a_b__x"}


def test_store_write_failure_is_a_readable_error(setup, monkeypatch):
    import sqlite3

    def locked(self, *args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SqliteMcpStore, "put_server", locked)
    path = _file(setup.tmp, {"loc": {"command": "local-server"}})
    code, out = _run(setup, "add", path, "--yes")
    assert code == 1
    assert "zygos mcp: couldn't update the MCP record (database is locked); try again" in out
    assert "Traceback" not in out


def test_store_read_failure_is_a_readable_error(setup, monkeypatch):
    from zygos.mcp.store import McpStoreUnavailable

    def unreadable(self):
        raise McpStoreUnavailable("mcp store unreadable (DatabaseError: file is not a database)")

    monkeypatch.setattr(SqliteMcpStore, "servers", unreadable)
    code, out = _run(setup, "list")
    assert code == 1
    assert "zygos mcp: mcp store unreadable (DatabaseError: file is not a database)" in out


def test_add_hints_trust_and_warns_over_20(setup):
    path = _file(setup.tmp, {"archon": {"url": "http://127.0.0.1:9/mcp"}})
    tools = [_tool(f"t{i}") for i in range(21)]
    code, out = _run(setup, "add", path, "--yes", list_remote=ListSpy(tools))
    assert code == 0
    assert ("trust the ones you want: zygos mcp trust archon/TOOL (or archon for all 21)"
            " — see zygos mcp list") in out
    assert TOOL_COUNT_WARNING in out


@pytest.mark.parametrize("raw", ['"abc"', "0", "true", "NaN", "1e309"])
def test_add_bad_timeout_is_a_readable_error(setup, raw):
    bad = setup.tmp / "bad.json"
    bad.write_text('{"mcpServers": {"slowsrv": {"command": "x", "timeout_s": ' + raw + "}}}")
    code, out = _run(setup, "add", str(bad), "--yes")
    assert code == 1
    assert out.startswith("zygos mcp: server 'slowsrv': timeout_s") and "Traceback" not in out
    assert _store(setup).servers() == {}


def test_add_turns_a_spec_validation_error_into_a_readable_one(setup, monkeypatch):
    import zygos.mcp.config as config_mod
    from zygos.mcp.types import ServerSpec

    def broken(**kwargs):
        return ServerSpec(**{**kwargs, "args": 5})  # a field pydantic rejects

    monkeypatch.setattr(config_mod, "ServerSpec", broken)
    path = _file(setup.tmp, {"odd": {"command": "x"}})
    code, out = _run(setup, "add", path, "--yes")
    assert code == 1 and out.startswith("zygos mcp: server 'odd': ")


def test_switching_a_server_back_on_clears_switched_off(setup):
    from zygos.mcp.store import ServerState

    path = _file(setup.tmp, {"rem": {"url": "http://127.0.0.1:9/mcp"}, "loc": {"command": "x"}})
    assert _run(setup, "add", path, "--yes", list_remote=ListSpy())[0] == 0
    store = _store(setup)
    for name in ("rem", "loc"):
        store.put_state(name, store.state(name).model_copy(
            update={"status": "stopped", "detail": "switched off"}))  # as zygos serve records it
        assert _run(setup, "on", name)[0] == 0
    _, out = _run(setup, "list")
    assert "switched off" not in out
    assert "status: not contacted yet" in out
    assert "status: not started — zygos serve starts it" in out
    assert store.state("rem").tools  # the tools last seen stay


def test_list_notes_clashes_only_among_servers_that_are_on(setup):
    store = _store(setup)
    from zygos.mcp.store import ServerState
    from zygos.mcp.types import ServerSpec

    for name, tools in (("a", [_tool("_x"), _tool("ok")]), ("a_", [_tool("x")])):
        store.put_server(ServerSpec(name=name, transport="http", url="http://127.0.0.1:9/mcp"))
        store.put_state(name, ServerState(tools=tools))
    _, out = _run(setup, "list")
    assert out.count("left out: name clash") == 2
    store.set_off("server", "a_", True)
    _, out = _run(setup, "list")
    assert "name clash" not in out
    assert "_x — on, not trusted" in out and "2 tools on" in out
