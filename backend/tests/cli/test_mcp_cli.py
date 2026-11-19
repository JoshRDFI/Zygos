"""`zygos mcp add | list | remove | on | off | trust | untrust` (MCP phase 1a, Task 8)."""

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
    assert "zygos mcp trust echo/" in out
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
