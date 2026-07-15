from __future__ import annotations

import asyncio

from zygos.api.duck import arm_duck, clear_duck_state, release_duck, stop_speech
from zygos.api.frames import AUDIO_OUT
from zygos.api.session import Session
from zygos.runtime.context import CancelToken, root_context
from zygos.runtime.events import InProcessEventBus


def _session() -> Session:
    return Session("s", root_context(InProcessEventBus()), created_at=0.0)


def _drain(session):
    out = []
    while not session.outbound.empty():
        out.append(session.outbound.get_nowait())
    return out


async def test_arm_duck_when_speaking_emits_duck_and_arms_timeout():
    s = _session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)
    assert s.ducked is True
    assert s.duck_timeout is not None and not s.duck_timeout.done()
    items = _drain(s)
    assert len(items) == 1
    assert items[0].channel == AUDIO_OUT and items[0].type == "tts.duck"
    assert items[0].payload == {"gain": 0.2}
    s.duck_timeout.cancel()
    await asyncio.sleep(0)  # let the cancelled timeout task settle


async def test_arm_duck_no_op_when_not_speaking():
    s = _session()  # speaking is False
    arm_duck(s, gain=0.2, timeout_s=5.0)
    assert s.ducked is False and s.duck_timeout is None
    assert _drain(s) == []


async def test_arm_duck_idempotent_when_already_ducked():
    s = _session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)
    first = s.duck_timeout
    _drain(s)
    arm_duck(s, gain=0.2, timeout_s=5.0)  # second onset while ducked
    assert s.duck_timeout is first  # not re-armed
    assert _drain(s) == []          # no second tts.duck
    s.duck_timeout.cancel()
    await asyncio.sleep(0)  # let the cancelled timeout task settle


async def test_release_duck_emits_unduck_and_cancels_timeout():
    s = _session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)
    timeout = s.duck_timeout
    _drain(s)
    release_duck(s)
    await asyncio.sleep(0)  # let the cancelled timeout task settle
    assert s.ducked is False and s.duck_timeout is None
    assert timeout.cancelled() or timeout.done()
    items = _drain(s)
    assert len(items) == 1 and items[0].type == "tts.unduck"
    assert items[0].payload == {"gain": 1.0}


async def test_release_duck_no_op_when_not_ducked():
    s = _session()
    release_duck(s)
    assert _drain(s) == []


async def test_duck_timeout_auto_unducks():
    s = _session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=0.02)
    await asyncio.sleep(0.06)
    assert s.ducked is False
    types = [i.type for i in _drain(s)]
    assert types == ["tts.duck", "tts.unduck"]


async def test_stop_speech_trips_active_turn_without_new_task():
    s = _session()
    token = CancelToken()
    s.active_cancel = token

    async def _never():
        await asyncio.Event().wait()

    s.active_task = asyncio.create_task(_never())
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)  # be ducked first
    _drain(s)
    stop_speech(s)
    await asyncio.sleep(0)  # let the cancelled duck-timeout task settle
    assert token.is_set is True          # hard stop tripped
    assert s.ducked is False             # duck state cleared
    assert s.duck_timeout is None        # timeout cancelled
    assert _drain(s) == []               # stop emits no tts.* frame itself
    s.active_task.cancel()
    try:
        await s.active_task
    except asyncio.CancelledError:
        pass


async def test_stop_speech_no_op_without_active_turn():
    s = _session()  # no active_task / active_cancel
    stop_speech(s)  # must not raise
    assert s.ducked is False


async def test_clear_duck_state_cancels_timeout_without_emitting():
    s = _session()
    s.speaking = True
    arm_duck(s, gain=0.2, timeout_s=5.0)
    timeout = s.duck_timeout
    _drain(s)
    clear_duck_state(s)
    await asyncio.sleep(0)  # let the cancelled timeout task settle
    assert s.ducked is False and s.duck_timeout is None
    assert timeout.cancelled() or timeout.done()
    assert _drain(s) == []  # no tts.unduck on a silent clear
