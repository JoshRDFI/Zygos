import asyncio
import sys

import pytest

from zygos.voice.plugin import Transcription
from zygos.voice.sidecar import SidecarHandle
from zygos.voice.types import SttEngineSpec

FAKE = SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt"))


async def test_start_connects_and_snapshot_reports_alive():
    h = SidecarHandle(FAKE)
    try:
        conn = await h.start()
        assert conn is h.connection
        await conn.send_control({"type": "health"})
        kind, body = await conn.recv()
        assert body["type"] == "health_ok"
        assert h.snapshot().alive is True
    finally:
        await h.aclose()
    assert h.snapshot().alive is False


async def test_killed_child_is_restarted_with_backoff():
    slept: list[float] = []
    h = SidecarHandle(FAKE, sleep=lambda s: slept.append(s) or asyncio.sleep(0))
    try:
        await h.start()
        # kill the child out from under the handle
        h._proc.kill()          # test reaches into the impl to simulate a crash
        await h._proc.wait()
        await h.ensure_alive()
        assert h.snapshot().restarts == 1
        assert slept and slept[0] > 0  # backed off before restart
        # the restarted worker still answers
        await h.connection.send_control({"type": "health"})
        _, body = await h.connection.recv()
        assert body["type"] == "health_ok"
    finally:
        await h.aclose()


async def test_restart_exhaustion_raises(monkeypatch):
    h = SidecarHandle(FAKE, sleep=lambda s: asyncio.sleep(0), max_restarts=1)
    try:
        await h.start()

        async def _always_fail():
            raise __import__("zygos.voice.errors", fromlist=["SidecarSpawnError"]).SidecarSpawnError("no")

        monkeypatch.setattr(h, "_spawn", _always_fail)
        h._proc.kill(); await h._proc.wait()
        with pytest.raises(Exception):
            for _ in range(3):
                await h.ensure_alive()
    finally:
        await h.aclose()


async def test_concurrent_ensure_alive_spawns_once():
    h = SidecarHandle(FAKE, sleep=lambda s: asyncio.sleep(0))
    try:
        await h.start()
        h._proc.kill(); await h._proc.wait()
        # fire many concurrent restart requests at the dead handle
        await asyncio.gather(*(h.ensure_alive() for _ in range(5)))
        assert h.snapshot().restarts == 1   # not 5
        await h.connection.send_control({"type": "health"})
        _, body = await h.connection.recv()
        assert body["type"] == "health_ok"
    finally:
        await h.aclose()


async def test_spec_env_reaches_child_process():
    spec = SttEngineSpec(
        name="fake",
        argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt"),
        env={"ZYGOS_FAKE_STT_TRANSCRIPT": "marco polo"},
    )
    h = SidecarHandle(spec)
    try:
        await h.start()
        tr = Transcription(h.connection)
        await tr.push(b"\x00\x00" * 8)
        await tr.endpoint()
        finals = [ev async for ev in tr.events() if ev.kind == "final"]
        assert finals and finals[-1].text == "marco polo"
    finally:
        await h.aclose()
