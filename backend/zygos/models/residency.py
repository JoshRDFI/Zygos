"""Residency: which local models are loaded (RFC-0013 §8).

Loads of Ollama models are serialised behind one lock. A model with a turn in
flight is never unloaded: a load that must unload it waits, holding the lock,
until that turn ends. Other providers (vLLM, llama.cpp) manage their own
lifecycle, so ``ensure_resident`` is a no-op for them.

**In-use hand-off.** ``ensure_resident`` counts the model in use *before* it
releases the lock, and records that count as a reservation held by the calling
task. ``turn(route)`` entered from the same task takes the reservation over
instead of counting again, so no load can unload the model between the two
calls. A reservation that no ``turn`` claims (the caller was cancelled, or fell
back) is released when the task ends, or replaced by that task's next
``ensure_resident``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol

from zygos.errors import ModelLoadFailed, ProviderError
from zygos.hardware.probe import HardwareSnapshot
from zygos.models.fit import FitLevel, VramContext, fit
from zygos.models.profile import ModelProfile, record
from zygos.models.store import ProfileStore
from zygos.providers.types import LOAD_TIMEOUT_S, OLLAMA_KEEP_ALIVE, OllamaRunning, ollama_name
from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import ModelLoaded
from zygos.services.router import RouteChoice

__all__ = ["LOAD_TIMEOUT_S", "OLLAMA_KEEP_ALIVE", "ResidencyManager"]

log = logging.getLogger("zygos.models")

_RANK: dict[FitLevel, int] = {"gpu": 0, "partial": 1, "no": 2, "unknown": 3}


class ResidencyCatalog(Protocol):
    """What residency reads from the model catalog."""

    async def hardware_now(self) -> HardwareSnapshot: ...

    def reserve_bytes(self) -> int: ...


class ResidencyManager:
    def __init__(
        self,
        provider_for: Callable[[str], Any | None],
        catalog: ResidencyCatalog,
        profiles: ProfileStore,
        *,
        clock: Callable[[], datetime],
        timer: Callable[[], float] = time.monotonic,
        load_timeout_s: float = LOAD_TIMEOUT_S,
        keep_alive: str = OLLAMA_KEEP_ALIVE,
        context: Callable[[], ExecutionContext] | None = None,
    ) -> None:
        self._provider_for = provider_for
        self._catalog = catalog
        self._profiles = profiles
        self._clock = clock
        self._timer = timer
        self._load_timeout_s = load_timeout_s
        self._keep_alive = keep_alive
        self._context = context
        self._lock = asyncio.Lock()
        self._in_flight: dict[str, int] = {}
        # Set when the model's count returns to 0; replaced when it leaves 0.
        self._idle: dict[str, asyncio.Event] = {}
        # task -> model it counted in use and no turn() has taken over yet.
        self._reserved: dict[asyncio.Task[Any], str] = {}
        self._watched: set[asyncio.Task[Any]] = set()
        self._preload: asyncio.Task[None] | None = None

    # -- in-use counts --------------------------------------------------------

    def _acquire(self, model: str) -> None:
        count = self._in_flight.get(model, 0)
        if count == 0:
            self._idle[model] = asyncio.Event()
        self._in_flight[model] = count + 1

    def _release(self, model: str) -> None:
        count = self._in_flight.get(model, 0) - 1
        if count > 0:
            self._in_flight[model] = count
            return
        self._in_flight.pop(model, None)
        idle = self._idle.pop(model, None)
        if idle is not None:
            idle.set()

    async def _wait_idle(self, model: str) -> None:
        while self._in_flight.get(model, 0) > 0:
            await self._idle[model].wait()

    def _reserve(self, model: str) -> None:
        """Count ``model`` in use for the current task until its turn() takes over."""
        task = asyncio.current_task()
        assert task is not None
        self._drop_reservation(task)
        self._acquire(model)
        self._reserved[task] = model
        if task not in self._watched:
            self._watched.add(task)
            task.add_done_callback(self._task_done)

    def _drop_reservation(self, task: asyncio.Task[Any]) -> None:
        model = self._reserved.pop(task, None)
        if model is not None:
            self._release(model)

    def _task_done(self, task: asyncio.Task[Any]) -> None:
        self._watched.discard(task)
        self._drop_reservation(task)

    @staticmethod
    def _key(route: RouteChoice) -> str | None:
        return ollama_name(route.model) if route.provider == "ollama" else None

    @asynccontextmanager
    async def turn(self, route: RouteChoice) -> AsyncIterator[None]:
        """Mark the route's model in use for the call. Counted on entry, before
        any await; released when the call ends or raises."""
        model = self._key(route)
        if model is None:
            yield
            return
        task = asyncio.current_task()
        if task is not None and self._reserved.get(task) == model:
            del self._reserved[task]  # take over ensure_resident's count
        else:
            self._acquire(model)
        try:
            yield
        finally:
            self._release(model)

    # -- loading --------------------------------------------------------------

    def _profile(self, model: str, name: str) -> ModelProfile | None:
        return self._profiles.get("ollama", name) or self._profiles.get("ollama", model)

    async def _running(self, ollama: Any) -> tuple[OllamaRunning, ...]:
        try:
            return await ollama.running_models()
        except ProviderError as exc:
            raise ModelLoadFailed(f"can't read Ollama's loaded models: {exc}", provider="ollama") from exc
        except Exception as exc:  # noqa: BLE001 - every load failure is a ProviderError
            raise ModelLoadFailed(f"can't read Ollama's loaded models: {exc!r}", provider="ollama") from exc

    async def _victims(self, profile: ModelProfile | None, others: list[OllamaRunning]) -> list[OllamaRunning]:
        """Loaded models to unload, idle ones first, largest first, until the
        model fits as well as it would with all of them gone."""
        if profile is None or not others:
            return []
        hardware = await self._catalog.hardware_now()
        reserve = self._catalog.reserve_bytes()

        def level(freed: int) -> FitLevel:
            # Loaded models count as not reclaimable: residency unloads them itself.
            return fit(profile, hardware, VramContext(reclaimable_bytes=freed, reserve_bytes=reserve)).level

        now = level(0)
        if now in ("gpu", "unknown"):
            return []
        goal = level(sum(r.size_vram for r in others))
        if _RANK[goal] >= _RANK[now]:
            return []  # unloading would not help
        order = sorted(others, key=lambda r: (self._in_flight.get(r.name, 0) > 0, -r.size_vram))
        victims: list[OllamaRunning] = []
        freed = 0
        for r in order:
            victims.append(r)
            freed += r.size_vram
            if level(freed) == goal:
                break
        return victims

    async def ensure_resident(
        self,
        ctx: ExecutionContext,
        route: RouteChoice,
        *,
        on_loading: Callable[[RouteChoice], None] | None = None,
    ) -> None:
        """Make sure the route's model is loaded and count it in use (see the
        module docstring). Raises ``ProviderError`` for every load failure."""
        name = self._key(route)
        if name is None:
            return
        ollama = self._provider_for("ollama")
        if ollama is None or not hasattr(ollama, "load"):
            return
        announced = False
        if self._lock.locked() and on_loading is not None:
            # Another load holds the lock: say "loading" now, while this turn waits.
            try:
                loaded = any(r.name == name for r in await ollama.running_models())
            except Exception:  # noqa: BLE001 - the check under the lock decides
                loaded = True
            if not loaded:
                on_loading(route)
                announced = True
        async with self._lock:
            running = await self._running(ollama)
            if any(r.name == name for r in running):
                self._reserve(name)
                return
            profile = self._profile(route.model, name)
            victims = await self._victims(profile, [r for r in running if r.name != name])
            if on_loading is not None and not announced:
                on_loading(route)
            evicted: list[str] = []
            for victim in victims:
                await self._wait_idle(victim.name)  # never unload under a turn
                try:
                    await ollama.unload(victim.name)
                except Exception as exc:  # noqa: BLE001 - the load decides the outcome
                    log.warning("can't unload %s: %s", victim.name, exc)
                    continue
                evicted.append(victim.name)
            started = self._timer()
            await self._load(ollama, name)
            load_ms = round((self._timer() - started) * 1000)
            self._reserve(name)
        self._record_load_ms(route.model, name, load_ms)
        await ctx.emit(ModelLoaded(provider="ollama", model=name, load_ms=load_ms,
                                   evicted=tuple(evicted)), source="models")

    async def _load(self, ollama: Any, name: str) -> None:
        try:
            async with asyncio.timeout(self._load_timeout_s):
                await ollama.load(name, keep_alive=self._keep_alive)
        except TimeoutError as exc:
            raise ModelLoadFailed(
                f"loading {name} timed out after {self._load_timeout_s:g}s", provider="ollama") from exc
        except ProviderError as exc:
            raise ModelLoadFailed(f"loading {name} failed: {exc}", provider="ollama") from exc
        except Exception as exc:  # noqa: BLE001 - every load failure is a ProviderError
            raise ModelLoadFailed(f"loading {name} failed: {exc!r}", provider="ollama") from exc

    def _record_load_ms(self, model: str, name: str, load_ms: int) -> None:
        profile = self._profile(model, name)
        if profile is None:
            return
        updated = record(profile, "performance.load_ms", load_ms, "measured", self._clock())
        if updated is profile:
            return
        try:
            self._profiles.save(updated)
        except OSError as exc:
            log.warning("load time for %s can't be saved: %s", name, exc)

    # -- background preload ---------------------------------------------------

    def preload(self, route: RouteChoice) -> None:
        """Load ``route`` in the background; a newer preload cancels this one."""
        previous = self._preload
        if previous is not None and not previous.done():
            previous.cancel()
        self._preload = asyncio.create_task(self._run_preload(route))

    async def _run_preload(self, route: RouteChoice) -> None:
        ctx = self._context() if self._context is not None else None
        if ctx is None:
            log.warning("preload of %s/%s skipped: no context", route.provider, route.model)
            return
        try:
            await self.ensure_resident(ctx, route)
        except Exception as exc:  # noqa: BLE001 - a preload never raises
            log.warning("preload of %s/%s failed: %s", route.provider, route.model, exc)

    async def preload_done(self) -> None:
        """Wait for the latest preload to finish (or be cancelled); never raises."""
        while self._preload is not None and not self._preload.done():
            task = self._preload
            await asyncio.wait([task])
