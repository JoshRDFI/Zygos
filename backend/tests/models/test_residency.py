"""ResidencyManager: serialised Ollama loads, no eviction mid-turn (RFC-0013 §8)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from zygos.errors import ProviderError, ProviderTimeout
from zygos.hardware.probe import Gpu, HardwareSnapshot
from zygos.models.profile import ModelProfile, record, resolve
from zygos.models.residency import LOAD_TIMEOUT_S, OLLAMA_KEEP_ALIVE, ResidencyManager
from zygos.models.store import ProfileStore
from zygos.providers.types import OllamaRunning
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus, ModelLoaded
from zygos.services.router import RouteChoice

GiB = 1024**3
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
TOTAL_VRAM = 16 * GiB


class FakeOllama:
    name = "ollama"

    def __init__(self, sizes: dict[str, int], loaded: tuple[str, ...] = ()) -> None:
        self.sizes = sizes
        self.running: list[str] = list(loaded)
        self.calls: list[tuple[str, str]] = []
        self.gates: dict[str, asyncio.Event] = {}
        self.fail: dict[str, BaseException] = {}
        self.load_started = asyncio.Event()

    async def running_models(self):
        return tuple(OllamaRunning(name=n, digest=f"d-{n}", size=self.sizes[n],
                                   size_vram=self.sizes[n]) for n in self.running)

    async def load(self, model: str, *, keep_alive: str) -> None:
        self.calls.append(("load", model))
        self.keep_alive = keep_alive
        self.load_started.set()
        if model in self.gates:
            await self.gates[model].wait()
        if model in self.fail:
            raise self.fail.pop(model)
        self.running.append(model)

    async def unload(self, model: str) -> None:
        self.calls.append(("unload", model))
        self.running.remove(model)


class FakeCatalog:
    def __init__(self, ollama: FakeOllama, *, gpu: bool = True) -> None:
        self.ollama = ollama
        self.gpu = gpu

    async def hardware_now(self) -> HardwareSnapshot:
        used = sum(self.ollama.sizes[n] for n in self.ollama.running)
        gpus = (Gpu(name="g", vram_total_bytes=TOTAL_VRAM, vram_free_bytes=TOTAL_VRAM - used),) if self.gpu else None
        return HardwareSnapshot(gpus=gpus, ram_total_bytes=64 * GiB, ram_available_bytes=48 * GiB,
                                cpu_model=None, cpu_cores=None, disk_path=None, disk_free_bytes=None,
                                scanned_at=NOW)

    def reserve_bytes(self) -> int:
        return 0


def _profile(name: str, size: int | None) -> ModelProfile:
    p = ModelProfile(provider="ollama", model=name, names=[name], digest=f"d-{name}")
    if size is not None:
        p = record(p, "performance.loaded_size_bytes", size, "measured", NOW)
    return p


class Rig:
    def __init__(self, tmp_path, sizes, loaded=(), *, profiled=None, gpu=True, load_timeout_s=LOAD_TIMEOUT_S,
                 times=None):
        self.ollama = FakeOllama(sizes, loaded)
        self.profiles = ProfileStore(tmp_path)
        for name in (sizes if profiled is None else profiled):
            self.profiles.save(_profile(name, sizes[name]))
        self.events: list = []
        self.bus = InProcessEventBus()

        async def collect(event):
            self.events.append(event.payload)

        self.bus.subscribe(collect)
        ticks = iter(times or [])
        self.manager = ResidencyManager(
            lambda name: self.ollama if name == "ollama" else None,
            FakeCatalog(self.ollama, gpu=gpu), self.profiles,
            clock=lambda: NOW, timer=lambda: next(ticks, 0.0),
            load_timeout_s=load_timeout_s, context=lambda: root_context(self.bus))

    def ctx(self):
        return root_context(self.bus)

    def loaded_events(self) -> list[ModelLoaded]:
        return [e for e in self.events if isinstance(e, ModelLoaded)]


def _r(model: str, provider: str = "ollama") -> RouteChoice:
    return RouteChoice(provider=provider, model=model)


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


async def test_already_loaded_makes_no_call(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB}, loaded=("a:latest",))
    await rig.manager.ensure_resident(rig.ctx(), _r("a"))  # untagged name means :latest
    assert rig.ollama.calls == []
    assert rig.loaded_events() == []


async def test_fits_alongside_loads_only(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB, "b:latest": 4 * GiB}, loaded=("a:latest",))
    loading: list[RouteChoice] = []
    await rig.manager.ensure_resident(rig.ctx(), _r("b:latest"), on_loading=loading.append)
    assert rig.ollama.calls == [("load", "b:latest")]
    assert rig.ollama.keep_alive == OLLAMA_KEEP_ALIVE == "30m"
    assert loading == [_r("b:latest")]
    assert rig.loaded_events()[0].evicted == ()


async def test_does_not_fit_unloads_the_other_then_loads(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))
    await rig.manager.ensure_resident(rig.ctx(), _r("b:latest"))
    assert rig.ollama.calls == [("unload", "a:latest"), ("load", "b:latest")]
    assert rig.loaded_events()[0].evicted == ("a:latest",)


async def test_unloads_largest_idle_first_and_only_as_many_as_needed(tmp_path):
    sizes = {"s:latest": 3 * GiB, "m:latest": 5 * GiB, "l:latest": 6 * GiB, "t:latest": 7 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("s:latest", "m:latest", "l:latest"))  # 2 GiB free
    await rig.manager.ensure_resident(rig.ctx(), _r("t:latest"))
    assert rig.ollama.calls == [("unload", "l:latest"), ("load", "t:latest")]


async def test_idle_model_goes_before_a_larger_busy_one(tmp_path):
    sizes = {"busy:latest": 8 * GiB, "idle:latest": 6 * GiB, "t:latest": 7 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("busy:latest", "idle:latest"))  # 2 GiB free
    async with rig.manager.turn(_r("busy:latest")):
        await rig.manager.ensure_resident(rig.ctx(), _r("t:latest"))
    assert rig.ollama.calls == [("unload", "idle:latest"), ("load", "t:latest")]


async def test_unknown_fit_evicts_nothing_and_just_loads(tmp_path):
    sizes = {"a:latest": 10 * GiB, "b:latest": 10 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("a:latest",), profiled=["a:latest"])  # b has no profile
    await rig.manager.ensure_resident(rig.ctx(), _r("b:latest"))
    assert rig.ollama.calls == [("load", "b:latest")]
    assert rig.loaded_events()[0].evicted == ()


async def test_no_gpu_is_unknown_fit_and_evicts_nothing(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",), gpu=False)
    await rig.manager.ensure_resident(rig.ctx(), _r("b:latest"))
    assert rig.ollama.calls == [("load", "b:latest")]


async def test_load_waits_for_the_turn_in_flight_on_the_model_it_must_unload(tmp_path):
    """Review Focus 2: a model with a turn in flight is never unloaded."""
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))
    turn_ends = asyncio.Event()
    loading: list[RouteChoice] = []

    async def turn_on_a():
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))
        async with rig.manager.turn(_r("a:latest")):
            await turn_ends.wait()
            assert rig.ollama.calls == []  # still loaded while the turn runs

    a_task = asyncio.create_task(turn_on_a())
    await _settle()
    b_task = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("b:latest"),
                                                             on_loading=loading.append))
    await _settle()
    assert not b_task.done()
    assert rig.ollama.calls == []
    assert loading == [_r("b:latest")]  # the waiting turn already shows "loading b…"
    turn_ends.set()
    await asyncio.wait_for(asyncio.gather(a_task, b_task), 1)
    assert rig.ollama.calls == [("unload", "a:latest"), ("load", "b:latest")]


async def test_reservation_hands_off_to_turn_so_no_load_slips_in_between(tmp_path):
    """ensure_resident counts the model in use before it releases the lock; turn()
    takes that count over, so a load that runs in between must wait for the turn."""
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))
    in_turn = asyncio.Event()
    finish = asyncio.Event()

    async def turn_on_a():
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))
        # Yield to the loop before entering the turn: b's load gets the lock here.
        await _settle()
        async with rig.manager.turn(_r("a:latest")):
            in_turn.set()
            await finish.wait()
            assert ("unload", "a:latest") not in rig.ollama.calls

    a_task = asyncio.create_task(turn_on_a())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    b_task = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")))
    await asyncio.wait_for(in_turn.wait(), 1)
    await _settle()
    assert not b_task.done()
    finish.set()
    await asyncio.wait_for(asyncio.gather(a_task, b_task), 1)
    assert rig.ollama.calls == [("unload", "a:latest"), ("load", "b:latest")]


async def test_reservation_never_claimed_is_released_when_its_task_ends(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))

    async def cancelled_before_turn():
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))
        await asyncio.sleep(3600)  # cancelled here: turn() is never entered

    task = asyncio.create_task(cancelled_before_turn())
    await _settle()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")), 1)
    assert rig.ollama.calls == [("unload", "a:latest"), ("load", "b:latest")]


async def test_turn_count_drops_when_the_turn_raises(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))
    await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))
    with pytest.raises(RuntimeError):
        async with rig.manager.turn(_r("a:latest")):
            raise RuntimeError("stream broke")
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")), 1)
    assert ("unload", "a:latest") in rig.ollama.calls


async def test_concurrent_loads_for_different_models_are_serialised(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB, "b:latest": 4 * GiB})
    rig.ollama.gates["a:latest"] = asyncio.Event()
    first = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("a:latest")))
    second = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")))
    await _settle()
    assert rig.ollama.calls == [("load", "a:latest")]  # b waits on the lock
    rig.ollama.gates["a:latest"].set()
    await asyncio.wait_for(asyncio.gather(first, second), 1)
    assert rig.ollama.calls == [("load", "a:latest"), ("load", "b:latest")]


async def test_load_error_raises_provider_error_and_releases_the_lock(tmp_path):
    """Review Focus 3: a failed load falls back like any hard failure; the next load works."""
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    rig.ollama.fail["a:latest"] = ProviderTimeout("ollama timed out", provider="ollama")
    with pytest.raises(ProviderError) as info:
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))
    assert info.value.retryable is False
    assert "a:latest" in str(info.value)
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("a:latest")), 1)
    assert rig.ollama.calls == [("load", "a:latest"), ("load", "a:latest")]


async def test_unexpected_load_exception_is_still_a_provider_error(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    rig.ollama.fail["a:latest"] = OSError("socket gone")
    with pytest.raises(ProviderError):
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))


async def test_load_that_hangs_times_out_as_provider_error_and_releases_the_lock(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB, "b:latest": 4 * GiB}, load_timeout_s=0.05)
    rig.ollama.gates["a:latest"] = asyncio.Event()  # never set
    with pytest.raises(ProviderError) as info:
        await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("a:latest")), 2)
    assert "timed out" in str(info.value)
    assert info.value.retryable is False
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")), 1)
    assert ("load", "b:latest") in rig.ollama.calls


async def test_running_models_failure_is_a_provider_error(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})

    async def down():
        raise ProviderError("ollama unreachable", provider="ollama")

    rig.ollama.running_models = down
    with pytest.raises(ProviderError):
        await rig.manager.ensure_resident(rig.ctx(), _r("a:latest"))


def test_load_timeout_constant():
    assert LOAD_TIMEOUT_S == 300.0


async def test_cancelled_ensure_resident_propagates_and_releases_the_lock(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB, "b:latest": 4 * GiB})
    rig.ollama.gates["a:latest"] = asyncio.Event()
    task = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("a:latest")))
    await rig.ollama.load_started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")), 1)


async def test_preload_twice_cancels_the_first_only_the_second_loads(tmp_path):
    """Review Focus 4: changing the default twice quickly."""
    rig = Rig(tmp_path, {"a:latest": 4 * GiB, "b:latest": 4 * GiB})
    rig.ollama.gates["a:latest"] = asyncio.Event()  # the first load hangs
    rig.manager.preload(_r("a:latest"))
    await rig.ollama.load_started.wait()
    rig.manager.preload(_r("b:latest"))
    await asyncio.wait_for(rig.manager.preload_done(), 1)
    assert rig.ollama.running == ["b:latest"]
    assert [e.model for e in rig.loaded_events()] == ["b:latest"]


async def test_preload_failure_is_logged_never_raised(tmp_path, caplog):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    rig.ollama.fail["a:latest"] = ProviderError("boom", provider="ollama")
    rig.manager.preload(_r("a:latest"))
    await asyncio.wait_for(rig.manager.preload_done(), 1)
    assert "a:latest" in caplog.text


async def test_preload_does_not_pin_the_model_after_it_finishes(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB})
    rig.manager.preload(_r("a:latest"))
    await asyncio.wait_for(rig.manager.preload_done(), 1)
    await _settle()
    await asyncio.wait_for(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")), 1)
    assert rig.ollama.calls == [("load", "a:latest"), ("unload", "a:latest"), ("load", "b:latest")]


async def test_load_time_is_measured_into_the_profile_and_model_loaded_emitted(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",),
              times=[100.0, 102.5])
    await rig.manager.ensure_resident(rig.ctx(), _r("b:latest"))
    [event] = rig.loaded_events()
    assert event.type == "model.loaded"
    assert (event.provider, event.model, event.load_ms, event.evicted) == (
        "ollama", "b:latest", 2500, ("a:latest",))
    reloaded = ProfileStore(tmp_path)
    reloaded.load_all()
    measured = resolve(reloaded.get("ollama", "b:latest"), "performance.load_ms")
    assert (measured.value, measured.source) == (2500, "measured")


async def test_non_ollama_route_is_a_no_op(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    await rig.manager.ensure_resident(rig.ctx(), _r("m", provider="vllm"))
    async with rig.manager.turn(_r("m", provider="vllm")):
        pass
    assert rig.ollama.calls == []
    assert rig.events == []


async def test_loaded_non_victim_turn_skips_the_lock_while_an_eviction_waits(tmp_path):
    """Review fix 1: X busy in session A, B waits to evict X for Y. D (Z loaded,
    not a victim) is not queued behind B; C (X, a victim) goes through the lock."""
    sizes = {"x:latest": 10 * GiB, "y:latest": 10 * GiB, "z:latest": 1 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("x:latest", "z:latest"))
    m = rig.manager
    a_ends = asyncio.Event()

    async def session_a():
        await m.ensure_resident(rig.ctx(), _r("x:latest"))
        async with m.turn(_r("x:latest")):
            await a_ends.wait()

    a = asyncio.create_task(session_a())
    await _settle()
    b = asyncio.create_task(m.ensure_resident(rig.ctx(), _r("y:latest")))
    await _settle()
    c = asyncio.create_task(m.ensure_resident(rig.ctx(), _r("x:latest")))
    d = asyncio.create_task(m.ensure_resident(rig.ctx(), _r("z:latest")))
    await _settle()
    assert d.done() and d.exception() is None  # Z's turn proceeds at once
    assert not b.done() and not c.done()
    assert rig.ollama.calls == []
    a_ends.set()
    await asyncio.wait_for(asyncio.gather(a, b, c), 1)
    # B unloads X (only X: Z is kept) and loads Y; C then reloads X, unloading
    # Y (idle once B's task ended). Z is never touched, X moves twice, no more.
    assert rig.ollama.calls == [("unload", "x:latest"), ("load", "y:latest"),
                                ("unload", "y:latest"), ("load", "x:latest")]


async def test_fast_path_rechecks_after_an_unload_it_raced(tmp_path):
    """A fast-path /api/ps read taken before an unload must not reserve the gone model."""
    sizes = {"x:latest": 10 * GiB, "y:latest": 10 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("x:latest",))
    m = rig.manager
    read_gate = asyncio.Event()
    real = rig.ollama.running_models
    first = True

    async def slow_first_read():
        nonlocal first
        snapshot = await real()
        if first:
            first = False
            await read_gate.wait()  # the snapshot says X is loaded; it goes stale here
        return snapshot

    rig.ollama.running_models = slow_first_read
    c = asyncio.create_task(m.ensure_resident(rig.ctx(), _r("x:latest")))
    await _settle()
    # Its own task, as a real turn is: the reservation ends with the task.
    await asyncio.wait_for(asyncio.create_task(m.ensure_resident(rig.ctx(), _r("y:latest"))), 1)
    read_gate.set()
    await asyncio.wait_for(c, 1)
    assert rig.ollama.calls == [("unload", "x:latest"), ("load", "y:latest"),
                                ("unload", "y:latest"), ("load", "x:latest")]


async def test_unneeded_victims_are_pruned(tmp_path):
    """Review fix 2: idle Z goes first by order, but unloading X alone suffices."""
    sizes = {"x:latest": 10 * GiB, "y:latest": 10 * GiB, "z:latest": 1 * GiB}
    rig = Rig(tmp_path, sizes, loaded=("x:latest", "z:latest"))  # 5 GiB free
    async with rig.manager.turn(_r("x:latest")):
        task = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("y:latest")))
        await _settle()
    await asyncio.wait_for(task, 1)
    assert rig.ollama.calls == [("unload", "x:latest"), ("load", "y:latest")]
    assert rig.loaded_events()[0].evicted == ("x:latest",)


# -- final fix wave: hold() for router-chosen answers; cancel_preload() -----------


async def test_hold_marks_a_model_in_use_until_released(tmp_path):
    """Minor (b): a model the router answered with (not the turn's pinned route)
    is never unloaded under its stream."""
    rig = Rig(tmp_path, {"a:latest": 10 * GiB, "b:latest": 10 * GiB}, loaded=("a:latest",))
    release = rig.manager.hold(_r("a"))  # untagged: same model
    b_task = asyncio.create_task(rig.manager.ensure_resident(rig.ctx(), _r("b:latest")))
    await _settle()
    assert not b_task.done()
    assert rig.ollama.calls == []
    release()
    release()  # idempotent
    await asyncio.wait_for(b_task, 1)
    assert rig.ollama.calls == [("unload", "a:latest"), ("load", "b:latest")]
    await _settle()  # b's unclaimed reservation is dropped when its task ends
    assert rig.manager._in_flight == {}


def test_hold_on_a_non_ollama_route_is_a_no_op(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    release = rig.manager.hold(_r("m", provider="vllm"))
    assert rig.manager._in_flight == {}
    release()


async def test_cancel_preload_stops_the_pending_load(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    rig.ollama.gates["a:latest"] = asyncio.Event()  # the load hangs
    rig.manager.preload(_r("a:latest"))
    await rig.ollama.load_started.wait()
    rig.manager.cancel_preload()
    await asyncio.wait_for(rig.manager.preload_done(), 1)
    assert rig.ollama.running == []
    assert rig.loaded_events() == []
    assert not rig.manager._lock.locked()
    rig.manager.cancel_preload()  # nothing pending: no-op


async def test_cancel_preload_with_none_pending_is_a_no_op(tmp_path):
    rig = Rig(tmp_path, {"a:latest": 4 * GiB})
    rig.manager.cancel_preload()
    await rig.manager.preload_done()
