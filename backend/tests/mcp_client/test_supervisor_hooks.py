"""McpSupervisor hooks used after a record write: ``sync_now``, ``restart`` and ``refresh``."""

from __future__ import annotations

import asyncio
import time

import pytest

from tests.mcp_client.test_supervisor import FakeSecrets, Harness, _local, _names, _remote, _tool, _until


@pytest.fixture
async def h(tmp_path):
    harness = Harness(tmp_path)
    yield harness
    for sup in harness.built:
        await sup.aclose()


async def test_sync_now_starts_newly_added_local(h):
    sup = h.make()
    await sup.start()
    h.fakes.local_tools["loc"] = [_tool("echo")]
    h.other.put_server(_local("loc"))  # added by the CLI or the web page; no turn follows
    sup.sync_now()
    await _until(lambda: len(h.fakes.locals) == 1 and h.fakes.locals[0].status == "running")
    await _until(lambda: h.fakes.list_count.get("loc") == 1)


async def test_restart_restarts_local_with_new_env(h):
    secrets = FakeSecrets({"mcp:loc:env:TOKEN": "v-1"})
    h.store.put_server(_local("loc", env_names=["TOKEN"]))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup = h.make(secrets=secrets)
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    first = h.fakes.locals[0]
    assert first.env == {"TOKEN": "v-1"}

    secrets.values["mcp:loc:env:TOKEN"] = "v-2"
    sup.restart("loc")
    await _until(lambda: len(h.fakes.locals) == 2 and h.fakes.locals[1].status == "running")
    await _until(lambda: first.stop_calls == 1)
    assert h.fakes.locals[1].env == {"TOKEN": "v-2"}
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    await asyncio.sleep(0.05)
    assert len(h.fakes.locals) == 2  # started once more, not again on later turns
    await _until(lambda: h.store.state("loc").status == "running")


async def test_restart_while_starting_stops_the_first_start(h):
    h.store.put_server(_local("loc"))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    h.fakes.local_delay["loc"] = 10
    sup = h.make()
    await sup.start()
    await _until(lambda: len(h.fakes.locals) == 1)
    h.fakes.local_delay["loc"] = 0
    sup.restart("loc")
    await _until(lambda: len(h.fakes.locals) == 2 and h.fakes.locals[1].status == "running")
    await _until(lambda: h.fakes.locals[0].stop_calls == 1)
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])


async def test_restart_unknown_or_off_server_does_nothing(h):
    h.store.put_server(_local("loc"))
    h.store.set_off("server", "loc", True)
    sup = h.make()
    await sup.start()
    sup.restart("loc")
    sup.restart("missing")
    await asyncio.sleep(0.05)
    assert h.fakes.locals == []


async def test_refresh_bounded(h):
    h.store.put_server(_remote("fast"))
    h.store.put_server(_remote("slow"))
    h.fakes.remote_tools["fast"] = [_tool("one")]
    h.fakes.remote_tools["slow"] = [_tool("late")]
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["fast__one", "slow__late"])

    h.fakes.remote_tools["fast"] = [_tool("one"), _tool("two")]
    h.fakes.remote_tools["slow"] = [_tool("late"), _tool("later")]
    gate = h.fakes.list_gate["slow"] = asyncio.Event()  # the slow server stops answering
    t0 = time.monotonic()
    await sup.refresh(0.3)
    elapsed = time.monotonic() - t0
    assert 0.25 <= elapsed < 2.0
    assert _names(sup.before_turn()) == ["fast__one", "fast__two", "slow__late"]
    assert h.fakes.list_calls.count("slow") == 2

    gate.set()  # the slow listing was left running, not cancelled
    await _until(lambda: "slow__later" in _names(sup.before_turn()))
    assert h.fakes.list_calls.count("slow") == 2


async def test_refresh_returns_early_when_listings_finish(h):
    h.store.put_server(_remote("fast"))
    h.fakes.remote_tools["fast"] = [_tool("one")]
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["fast__one"])
    h.fakes.remote_tools["fast"] = [_tool("one"), _tool("two")]
    t0 = time.monotonic()
    await sup.refresh(5.0)
    assert time.monotonic() - t0 < 1.0
    assert _names(sup.before_turn()) == ["fast__one", "fast__two"]


async def test_refresh_lists_running_local_now(h):
    h.store.put_server(_local("loc"))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup = h.make()
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    h.fakes.local_tools["loc"] = [_tool("echo"), _tool("grown")]
    await sup.refresh(5.0)
    assert _names(sup.before_turn()) == ["loc__echo", "loc__grown"]


async def test_hooks_after_close_do_nothing(h):
    sup = h.make()
    await sup.start()
    await sup.aclose()
    h.other.put_server(_local("loc"))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup.sync_now()
    sup.restart("loc")
    await sup.refresh(0.1)
    await asyncio.sleep(0.05)
    assert h.fakes.locals == []


async def test_refresh_with_no_servers_returns_at_once(h):
    sup = h.make()
    await sup.start()
    t0 = time.monotonic()
    await sup.refresh(5.0)
    assert time.monotonic() - t0 < 0.5


async def test_restart_remote_lists_again_with_new_headers(h):
    secrets = FakeSecrets({"mcp:arch:header:Authorization": "v-1"})
    h.store.put_server(_remote("arch", header_names=["Authorization"]))
    h.fakes.remote_tools["arch"] = [_tool("find")]
    sup = h.make(secrets=secrets)
    await sup.start()
    await _until(lambda: _names(sup.before_turn()) == ["arch__find"])
    secrets.values["mcp:arch:header:Authorization"] = "v-2"
    sup.restart("arch")
    assert _names(sup.before_turn()) == ["arch__find"]  # the tools last seen stay offered meanwhile
    await _until(lambda: h.fakes.list_calls.count("arch") == 2)
    assert h.fakes.headers_seen[-1] == {"Authorization": "v-2"}


async def test_restart_retries_a_local_failed_on_its_secrets(h):
    secrets = FakeSecrets({"mcp:loc:env:TOKEN": "v-1"}, locked={"loc"})
    h.store.put_server(_local("loc", env_names=["TOKEN"]))
    h.fakes.local_tools["loc"] = [_tool("echo")]
    sup = h.make(secrets=secrets)
    await sup.start()
    await _until(lambda: h.store.state("loc").status == "failed")
    assert h.fakes.locals == []
    secrets.locked = set()
    sup.restart("loc")
    await _until(lambda: _names(sup.before_turn()) == ["loc__echo"])
    assert h.fakes.locals[0].env == {"TOKEN": "v-1"}


async def test_refresh_retries_a_remote_failed_on_its_secrets(h):
    secrets = FakeSecrets({"mcp:arch:header:Authorization": "v-1"}, locked={"arch"})
    h.store.put_server(_remote("arch", header_names=["Authorization"]))
    h.fakes.remote_tools["arch"] = [_tool("find")]
    sup = h.make(secrets=secrets)
    await sup.start()
    await _until(lambda: h.store.state("arch").status == "failed")
    secrets.locked = set()
    await sup.refresh(5.0)
    assert _names(sup.before_turn()) == ["arch__find"]
    assert h.fakes.headers_seen[-1] == {"Authorization": "v-1"}
