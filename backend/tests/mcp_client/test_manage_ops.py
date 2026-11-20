"""Listing, removing, switching, trusting, secrets and timeouts on the MCP record
(shared by the CLI and the web page)."""

from __future__ import annotations

import logging
import math

import pytest

from zygos.mcp.config import zygos_tool_name
from zygos.mcp.manage import (
    ManageError, find_server, find_tool, list_view, presence, remove_server, resolve_target, set_secret,
    set_timeout, switch_server, switch_tool, trust_one, trust_server, trust_tool, untrust_server, untrust_tool,
)
from zygos.mcp.store import ServerState, SqliteMcpStore, TrustEntry
from zygos.mcp.supervisor import TOOL_COUNT_WARNING
from zygos.mcp.types import SeenTool, ServerSpec
from zygos.secrets import SecretStoreError
from zygos.secrets.types import Presence

SECRET = "Bearer s3cret"


class Secrets:
    """An in-memory secret store with ``presence``; ``broken`` makes every call raise."""

    def __init__(self, values: dict[str, str] | None = None, *, broken: bool = False) -> None:
        self.values = dict(values or {})
        self.broken = broken
        self.deleted: list[str] = []

    def _check(self) -> None:
        if self.broken:
            raise SecretStoreError("the keychain went away")

    def get(self, handle):
        self._check()
        return self.values.get(handle)

    def set(self, handle, value):
        self._check()
        self.values[handle] = value

    def delete(self, handle):
        self._check()
        self.deleted.append(handle)
        self.values.pop(handle, None)

    def presence(self, handle):
        self._check()
        return Presence("set" if handle in self.values else "not_set")


def _tool(name: str, description: str | None = None, problem: str | None = None) -> SeenTool:
    return SeenTool(
        name=name, description=description or f"{name} things.",
        input_schema={"type": "object", "properties": {}}, problem=problem,
    )


def _remote(name: str = "arch", **kw) -> ServerSpec:
    return ServerSpec(name=name, transport="http", url="http://127.0.0.1:9/mcp", **kw)


def _local(name: str = "loc", **kw) -> ServerSpec:
    return ServerSpec(name=name, transport="stdio", command="run-it", **kw)


@pytest.fixture
def store(tmp_path):
    return SqliteMcpStore(tmp_path / "preferences.db")


def _seed(store, spec, tools, **state):
    store.put_server(spec)
    store.put_state(spec.name, ServerState(status="reachable", tools=tools, **state))


# ---- list_view ------------------------------------------------------------------------


def test_list_view_shapes(store):
    trusted, changed, broken = _tool("a"), _tool("b", "b now"), _tool("c", problem="its input schema is unusable")
    _seed(store, _remote(header_names=["Authorization"]), [trusted, changed, broken], era="2025-06-18")
    trust_one(store, "arch", trusted)
    trust_one(store, "arch", _tool("b", "b before"))

    view = list_view(store, Secrets(), mcp_installed=lambda: True)

    assert view.installed is True
    (server,) = view.servers
    assert server.name == "arch" and server.transport == "http" and server.local is False
    assert server.runs == "This connects to http://127.0.0.1:9/mcp"
    assert server.on is True and server.status == "reachable" and server.status_word == "reachable"
    assert server.era == "2025-06-18" and server.timeout_s == 120.0
    assert server.trusted_server is False
    tools = {t.server_tool: t for t in server.tools}
    assert [t.trust for t in server.tools] == ["trusted", "changed", "asks"]
    assert tools["a"].zname == zygos_tool_name("arch", "a")
    assert tools["a"].was is None and tools["a"].now is None and tools["a"].on is True
    assert (tools["b"].was, tools["b"].now) == ("b before", "b now")
    assert tools["b"].schema_changed is False and tools["b"].on is True
    assert tools["c"].on is False and tools["c"].problem == "its input schema is unusable"
    assert server.tools_on == 2 and view.tools_on == 2
    assert view.warn is False and view.warning is None


def test_list_view_claims_and_switched_off_tool(store):
    seen = SeenTool(
        name="wipe", description="Wipes.", input_schema={"type": "object"},
        annotations={"destructiveHint": True, "readOnlyHint": False},
    )
    _seed(store, _remote(), [seen, _tool("keep")])
    store.set_off("tool", zygos_tool_name("arch", "wipe"), True, server="arch")
    (server,) = list_view(store, Secrets(), mcp_installed=lambda: True).servers
    wipe = server.tools[0]
    assert wipe.claims == ["destructive"] and wipe.on is False
    assert server.tools_on == 1


def test_list_view_secrets_presence_never_values(store):
    store.put_server(_remote(header_names=["Authorization", "X-Missing"]))
    secrets = Secrets({"mcp:arch:header:Authorization": SECRET})
    view = list_view(store, secrets, mcp_installed=lambda: True)
    (server,) = view.servers
    assert server.secrets == {"Authorization": "set", "X-Missing": "not set"}
    assert server.secret_reasons == {} and server.secrets_note is None
    assert "s3cret" not in view.model_dump_json()
    assert "s3cret" not in repr(view)


def test_list_view_secret_store_failure_reads_unknown_with_reason(store):
    store.put_server(_local(env_names=["TOKEN"]))
    (server,) = list_view(store, Secrets(broken=True), mcp_installed=lambda: True).servers
    assert server.secrets == {"TOKEN": "unknown"}
    assert server.secret_reasons == {"TOKEN": "the keychain went away"}
    assert server.secrets_note == "the keychain went away"


def test_presence_maps_states():
    secrets = Secrets({"mcp:s:env:A": "v"})
    assert presence(secrets, "mcp:s:env:A") == ("set", None)
    assert presence(secrets, "mcp:s:env:B") == ("not set", None)
    assert presence(Secrets(broken=True), "mcp:s:env:A") == ("unknown", "the keychain went away")

    class Unknown:
        def presence(self, handle):
            return Presence("unknown", "no secret store here")

    assert presence(Unknown(), "mcp:s:env:A") == ("unknown", "no secret store here")


def test_list_view_off_server_reads_off(store):
    _seed(store, _local(), [_tool("echo")])
    switch_server(store, "loc", False, clock=lambda: 100.0)
    (server,) = list_view(store, Secrets(), mcp_installed=lambda: True).servers
    assert server.on is False and server.status_word == "off"
    assert server.status == "reachable"  # the recorded status is kept as it was
    assert server.tools_on == 0


def test_list_view_warn_over_twenty(store):
    _seed(store, _remote(), [_tool(f"t{i}") for i in range(21)])
    view = list_view(store, Secrets(), mcp_installed=lambda: True)
    assert view.tools_on == 21 and view.warn is True and view.warning == TOOL_COUNT_WARNING


def test_list_view_twenty_does_not_warn(store):
    _seed(store, _remote(), [_tool(f"t{i}") for i in range(20)])
    view = list_view(store, Secrets(), mcp_installed=lambda: True)
    assert view.warn is False and view.warning is None


def test_list_view_not_installed(store):
    view = list_view(store, Secrets(), mcp_installed=lambda: False)
    assert view.installed is False and view.servers == [] and view.tools_on == 0


def test_list_view_sorted_by_name(store):
    for name in ("zed", "alpha"):
        store.put_server(_remote(name))
    assert [s.name for s in list_view(store, Secrets(), mcp_installed=lambda: True).servers] == ["alpha", "zed"]


# ---- find, resolve ------------------------------------------------------------------


def test_find_server_not_found(store):
    with pytest.raises(ManageError) as caught:
        find_server(store, "nope")
    assert caught.value.kind == "not_found" and caught.value.reason == "no server nope"


def test_find_tool_maps_zname_back(store):
    seen = _tool("do-it.now")
    _seed(store, _remote("my server"), [_tool("other"), seen])
    spec, found = find_tool(store, zygos_tool_name("my server", "do-it.now"))
    assert spec.name == "my server" and found == seen
    with pytest.raises(ManageError) as caught:
        find_tool(store, "my_server__missing")
    assert caught.value.kind == "not_found"


def test_resolve_target_longest_server_name_wins(store):
    store.put_server(_remote("a"))
    store.put_server(_remote("a/b"))
    assert resolve_target(store, "a/b")[0].name == "a/b"
    assert resolve_target(store, "a/b/tool") == (store.servers()["a/b"], "tool")
    assert resolve_target(store, "a/x") == (store.servers()["a"], "x")
    with pytest.raises(ManageError) as caught:
        resolve_target(store, "zz/tool")
    assert caught.value.kind == "not_found" and caught.value.reason == "no server zz"


# ---- remove, switch, trust ---------------------------------------------------------------


def test_remove_server_deletes_secrets_and_notes_failures(store):
    store.put_server(_remote(header_names=["Authorization"]))
    secrets = Secrets({"mcp:arch:header:Authorization": SECRET})
    assert remove_server(store, secrets, "arch") == []
    assert store.servers() == {} and secrets.values == {}
    store.put_server(_remote(header_names=["Authorization"]))
    notes = remove_server(store, Secrets(broken=True), "arch")
    assert notes == ["arch: could not delete the secret Authorization: the keychain went away"]
    with pytest.raises(ManageError) as caught:
        remove_server(store, secrets, "arch")
    assert caught.value.kind == "not_found"


def test_switch_tool_needs_a_seen_tool_unless_switching_back_on(store):
    store.put_server(_local())
    with pytest.raises(ManageError) as caught:
        switch_tool(store, "loc", "echo", False)
    assert caught.value.kind == "not_found"
    assert caught.value.reason == "no tool echo seen on loc yet — its tools are listed when zygos serve starts it"
    store.set_off("tool", "loc__echo", True, server="loc")
    switch_tool(store, "loc", "echo", True)  # an off tool can always be switched back on
    assert "tool:loc__echo" not in store.off()


def test_switch_server_round_trip(store):
    store.put_server(_remote())
    switch_server(store, "arch", False, clock=lambda: 1.0)
    assert "server:arch" in store.off()
    switch_server(store, "arch", True, clock=lambda: 2.0)
    assert "server:arch" not in store.off()


def test_trust_and_untrust(store):
    _seed(store, _remote(), [_tool("a"), _tool("b")])
    entry = trust_tool(store, "arch", "a")
    assert isinstance(entry, TrustEntry) and entry.via == "tool"
    assert len(trust_server(store, "arch")) == 2
    assert "arch" in store.trusted_servers()
    trust_tool(store, "arch", "a")  # trusted on its own again: kept after untrusting the server
    assert untrust_server(store, "arch") == ["arch__a"]
    assert untrust_tool(store, "arch", "a") is True
    assert untrust_tool(store, "arch", "a") is False
    with pytest.raises(ManageError) as caught:
        trust_tool(store, "arch", "missing")
    assert caught.value.reason == "no tool missing seen on arch yet"


def test_trust_server_without_tools_not_found(store):
    store.put_server(_remote())
    with pytest.raises(ManageError) as caught:
        trust_server(store, "arch")
    assert caught.value.kind == "not_found" and caught.value.reason == "no tools seen on arch yet"


# ---- secrets, timeout ------------------------------------------------------------------


def test_set_secret_stores_the_named_handle(store):
    store.put_server(_local(env_names=["TOKEN"]))
    secrets = Secrets()
    set_secret(store, secrets, "loc", "TOKEN", "v-1")
    assert secrets.values == {"mcp:loc:env:TOKEN": "v-1"}


def test_set_secret_unknown_name_not_found(store):
    store.put_server(_local(env_names=["TOKEN"]))
    secrets = Secrets()
    with pytest.raises(ManageError) as caught:
        set_secret(store, secrets, "loc", "OTHER", "v-1")
    assert caught.value.kind == "not_found" and caught.value.reason == "no secret OTHER on loc"
    assert secrets.values == {}
    with pytest.raises(ManageError) as caught:
        set_secret(store, secrets, "gone", "TOKEN", "v-1")
    assert caught.value.reason == "no server gone"


def test_set_secret_never_in_error(store, caplog):
    store.put_server(_remote(header_names=["Authorization"]))
    marker = "Bearer MARKER-9f2c"
    caplog.set_level(logging.DEBUG)
    with pytest.raises(ManageError) as caught:
        set_secret(store, Secrets(broken=True), "arch", "Authorization", marker)
    exc = caught.value
    assert exc.kind == "unavailable"
    assert exc.reason == "the secret Authorization can't be stored: the keychain went away"
    for text in (str(exc), repr(exc), exc.reason, *exc.notes, caplog.text):
        assert "MARKER" not in text
    assert exc.__cause__ is None and exc.__suppress_context__


def test_set_timeout_keeps_trust(store):
    _seed(store, _remote(), [_tool("a")])
    trust_one(store, "arch", _tool("a"))
    store.set_off("tool", "arch__b", True, server="arch")
    spec = set_timeout(store, "arch", 30)
    assert spec.timeout_s == 30.0 and store.servers()["arch"].timeout_s == 30.0
    assert "arch__a" in store.trust_entries()
    assert "tool:arch__b" in store.off()
    assert store.state("arch").tools == [_tool("a")]


@pytest.mark.parametrize("value", [0, math.nan, 601, -1, True, "30", None])
def test_set_timeout_rejects_zero_nan_and_601(store, value):
    store.put_server(_remote())
    with pytest.raises(ManageError) as caught:
        set_timeout(store, "arch", value)
    assert caught.value.kind == "invalid"
    assert "at most 600" in caught.value.reason
    assert store.servers()["arch"].timeout_s == 120.0
