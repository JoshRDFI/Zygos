import pytest

from zygos.api.frames import CHAT, Frame
from zygos.api.session import Session, SessionRegistry, SessionState
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus


def _registry():
    bus = InProcessEventBus()
    counter = {"n": 0}

    def new_id():
        counter["n"] += 1
        return f"id-{counter['n']}"

    return SessionRegistry(
        new_context=lambda sid: root_context(bus, session_id=sid),
        clock=lambda: 100.0,
        new_id=new_id,
    )


def test_create_returns_session_with_matching_run_id_trail():
    reg = _registry()
    s = reg.create()
    assert reg.get(s.id) is s
    assert s.root.session_id == s.id
    assert reg.get_by_run_id(s.root.run_id) is s


def test_snapshot_is_frozen_and_has_no_privileged_handles():
    reg = _registry()
    s = reg.create()
    snap = s.snapshot()
    assert isinstance(snap, SessionState)
    assert snap.id == s.id
    assert snap.turn_status == "idle"
    assert snap.connected is False
    with pytest.raises(Exception):
        snap.turn_count = 5


def test_begin_end_turn_tracks_status_and_count():
    reg = _registry()
    s = reg.create()
    s.begin_turn()
    assert s.turn_status == "running"
    assert s.turn_count == 1
    s.end_turn()
    assert s.turn_status == "idle"
    assert s.turn_count == 1


def test_enqueue_and_count_and_list():
    reg = _registry()
    s = reg.create()
    s.enqueue(Frame(channel=CHAT, type="token", payload={"text": "x"}))
    assert s.outbound.get_nowait().payload == {"text": "x"}
    assert reg.count() == 1
    assert [st.id for st in reg.list()] == [s.id]


def test_delete_trips_active_turn_and_removes():
    reg = _registry()
    s = reg.create()
    token = CancelToken()
    s.active_cancel = token

    async def _never_done():
        await CancelToken().wait()

    import asyncio
    loop = asyncio.new_event_loop()
    s.active_task = loop.create_task(_never_done())
    s.ducked = True
    duck_timeout = loop.create_task(_never_done())
    s.duck_timeout = duck_timeout
    assert reg.delete(s.id) is True
    assert token.is_set is True
    # delete() is the sole teardown of the abandoned session on WS disconnect,
    # so it must also clear any open duck window.
    assert s.ducked is False
    assert s.duck_timeout is None
    assert reg.get(s.id) is None
    assert reg.delete(s.id) is False
    s.active_task.cancel()
    loop.close()


def test_get_by_run_id_unknown_returns_none():
    reg = _registry()
    reg.create()
    assert reg.get_by_run_id("nope") is None
