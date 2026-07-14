"""SidecarHandle: subprocess supervision for a voice sidecar worker.

Spawns the worker, connects over IPC, monitors liveness, restarts it with
exponential backoff on crash, and kills it (process-group) on shutdown.
"""
from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from typing import Awaitable, Callable

from zygos.voice.errors import SidecarCrashed, SidecarSpawnError
from zygos.voice.ipc import IpcConnection, Listener, listen
from zygos.voice.types import SttEngineSpec

_ACCEPT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class SidecarState:
    alive: bool
    restarts: int
    last_error: str | None
    device: str
    engine: str


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):  # pragma: no cover
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class SidecarHandle:
    def __init__(
        self,
        spec: SttEngineSpec,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_restarts: int = 3,
        backoff_base_s: float = 0.05,
    ) -> None:
        self._spec = spec
        self._sleep = sleep
        self._max_restarts = max_restarts
        self._backoff = backoff_base_s
        self._listener: Listener | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._conn: IpcConnection | None = None
        self._restarts = 0
        self._last_error: str | None = None
        self._closed = False

    @property
    def connection(self) -> IpcConnection:
        if self._conn is None:
            raise SidecarCrashed("sidecar not started")
        return self._conn

    async def start(self) -> IpcConnection:
        await self._spawn()
        return self.connection

    async def _spawn(self) -> None:
        if self._listener is None:
            self._listener = await listen()
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._spec.argv, self._listener.address,
                stdin=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            conn = await asyncio.wait_for(self._listener.accept(), _ACCEPT_TIMEOUT_S)
        except (OSError, asyncio.TimeoutError) as exc:
            self._last_error = str(exc)
            raise SidecarSpawnError(f"failed to start {self._spec.name}: {exc}") from exc
        if self._conn is not None:
            # drop the stale (dead-process) connection: asyncio.Server.wait_closed()
            # waits for every accepted connection to be dropped, so leaving this open
            # would hang the listener's close() on the next aclose()/restart.
            await self._conn.close()
        self._conn = conn

    def _child_dead(self) -> bool:
        return self._proc is None or self._proc.returncode is not None

    async def ensure_alive(self) -> None:
        if self._closed or not self._child_dead():
            return
        while self._restarts < self._max_restarts:
            self._restarts += 1
            await self._sleep(self._backoff * (2 ** (self._restarts - 1)))
            try:
                await self._spawn()
                return
            except SidecarSpawnError as exc:
                self._last_error = str(exc)
        raise SidecarCrashed(f"{self._spec.name} exhausted {self._max_restarts} restarts")

    def snapshot(self) -> SidecarState:
        return SidecarState(
            alive=not self._child_dead() and not self._closed,
            restarts=self._restarts,
            last_error=self._last_error,
            device=self._spec.device,
            engine=self._spec.name,
        )

    async def aclose(self) -> None:
        self._closed = True
        if self._proc is not None and self._proc.returncode is None:
            _kill_process_group(self._proc)
            try:
                await self._proc.wait()
            except ProcessLookupError:  # pragma: no cover
                pass
        if self._conn is not None:
            await self._conn.close()
        if self._listener is not None:
            await self._listener.close()
