"""Planning, saving and listing an add (shared by the CLI and the web page)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from zygos.mcp.config import parse_servers
from zygos.mcp.manage import AddPlan, ManageError, list_after_add, plan_add, save_server
from zygos.mcp.store import SqliteMcpStore
from zygos.secrets import SecretStoreError

ARCHON = json.dumps({"mcpServers": {"archon": {
    "url": "http://localhost:8051/mcp", "headers": {"Authorization": "Bearer x"},
}}})


class MemorySecrets:
    """An in-memory secret store; ``fail_on`` handles raise on ``set``."""

    def __init__(self, values: dict[str, str] | None = None, fail_on: frozenset[str] = frozenset()) -> None:
        self.values = dict(values or {})
        self.fail_on = fail_on
        self.undeletable: set[str] = set()

    def status(self):
        return SimpleNamespace(available=True, why_unavailable=None)

    def get(self, handle):
        return self.values.get(handle)

    def set(self, handle, value):
        if handle in self.fail_on:
            raise SecretStoreError("the keychain went away")
        self.values[handle] = value

    def delete(self, handle):
        if handle in self.undeletable:
            raise SecretStoreError("locked")
        self.values.pop(handle, None)


@pytest.fixture
def store(tmp_path):
    return SqliteMcpStore(tmp_path / "preferences.db")


def test_plan_add_describes_without_values(store):
    plan = plan_add(store, ARCHON)
    assert isinstance(plan, AddPlan) and plan.problems == []
    (planned,) = plan.servers
    assert planned.name == "archon" and planned.transport in ("http", "sse")
    assert planned.runs == "This connects to http://localhost:8051/mcp"
    assert planned.secret_names == ["Authorization"]
    assert planned.replaces is False and planned.old_runs is None
    assert "Bearer x" not in repr(plan)
    assert all("Bearer x" not in p.model_dump_json() for p in plan.servers)
    assert plan.items[0].secrets  # the values are kept for saving


def test_plan_add_lists_unused_keys_sorted(store):
    text = json.dumps({"mcpServers": {"s": {"command": "run", "zeta": 1, "alpha": 2}}})
    assert plan_add(store, text).servers[0].unused == ["alpha", "zeta"]


def test_plan_add_flags_replace_with_old_runs(store):
    store.put_server(parse_servers(ARCHON)[0].spec)
    text = json.dumps({"mcpServers": {"archon": {"url": "http://localhost:9/mcp"}}})
    (planned,) = plan_add(store, text).servers
    assert planned.replaces is True
    assert planned.old_runs == "This connects to http://localhost:8051/mcp"
    assert planned.runs == "This connects to http://localhost:9/mcp"


def test_plan_add_bad_json_is_invalid(store):
    with pytest.raises(ManageError) as caught:
        plan_add(store, "{not json sk-secret")
    assert caught.value.kind == "invalid"
    assert caught.value.reason.startswith("not valid JSON")
    assert str(caught.value) == caught.value.reason


def test_plan_add_over_64k_is_too_large(store):
    text = json.dumps({"mcpServers": {"s": {"command": "run", "note": "x" * (64 * 1024)}}})
    with pytest.raises(ManageError) as caught:
        plan_add(store, text)
    assert caught.value.kind == "too_large"


def test_plan_add_name_problems_listed(store):
    text = json.dumps({"mcpServers": {"my server": {"command": "a"}, "my_server": {"command": "b"}}})
    assert plan_add(store, text).problems


def _remote(headers: dict[str, str]):
    return parse_servers(json.dumps({"mcpServers": {"arch": {
        "url": "http://127.0.0.1:9/mcp", "headers": headers,
    }}}))[0]


def test_save_server_rolls_back_secrets_on_failure(store):
    first = _remote({"Authorization": "sk-new", "X-Fail": "v"})
    secrets = MemorySecrets(
        {"mcp:arch:header:Authorization": "sk-old"}, fail_on=frozenset({"mcp:arch:header:X-Fail"})
    )
    with pytest.raises(ManageError) as caught:
        save_server(store, secrets, first, None)
    assert caught.value.kind == "unavailable"
    assert caught.value.reason == "its secrets can't be stored: the keychain went away"
    assert caught.value.notes == ["arch: the secrets saved before the failure were restored"]
    assert secrets.values == {"mcp:arch:header:Authorization": "sk-old"}
    assert store.servers() == {}


def test_save_server_replace_deletes_dropped_secret_handles(store):
    old = _remote({"Authorization": "sk-old", "X-Other": "v-2"})
    secrets = MemorySecrets()
    assert save_server(store, secrets, old, None) == []
    new = _remote({"Authorization": "sk-new"})
    assert save_server(store, secrets, new, old.spec) == []
    assert secrets.values == {"mcp:arch:header:Authorization": "sk-new"}
    assert store.servers()["arch"].header_names == ["Authorization"]


def test_save_server_reports_undeletable_dropped_secret(store):
    old = _remote({"Authorization": "a", "X-Other": "b"})
    secrets = MemorySecrets()
    save_server(store, secrets, old, None)
    secrets.undeletable.add("mcp:arch:header:X-Other")
    notes = save_server(store, secrets, _remote({"Authorization": "c"}), old.spec)
    assert notes == ["arch: could not delete the secret X-Other: locked"]


def _list(store, item, list_remote, **kwargs):
    return asyncio.run(list_after_add(
        store, item.spec, item, list_remote=list_remote, mcp_installed=lambda: True,
        clock=lambda: 100.0, **kwargs,
    ))


def test_list_after_add_timeout_records_unreachable(store):
    item = _remote({})
    store.put_server(item.spec)

    async def silent(spec, headers, *, era, discover):
        await asyncio.sleep(30)

    outcome = _list(store, item, silent, cap_s=0.1)
    assert "no answer within" in outcome
    assert outcome.startswith("arch: added, but its tools couldn't be listed: no answer within 0.1 s")
    state = store.state("arch")
    assert state.status == "unreachable" and "no answer within" in state.detail


def test_list_after_add_success_records_tools_and_passes_headers(store):
    from zygos.mcp.types import SeenTool
    from zygos.mcp.wire import ListResult

    item = _remote({"Authorization": "sk-1"})
    store.put_server(item.spec)
    seen: dict = {}

    async def ok(spec, headers, *, era, discover):
        seen.update(headers)
        return ListResult(era="2025-11-25", discover=None, tools=[SeenTool(name="find", description="", input_schema={})], ttl_s=None)

    outcome = _list(store, item, ok)
    assert seen == {"Authorization": "sk-1"}
    assert outcome.splitlines()[0] == "arch: added — 1 tool listed (protocol 2025-11-25)"
    assert "zygos mcp trust arch/TOOL" in outcome
    assert store.state("arch").status == "reachable"
