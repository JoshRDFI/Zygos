"""Shared cancel-watch primitive for sidecar workers.

A worker producing an utterance's frames must stay responsive to a `cancel`
control on the shared connection. `run_with_cancel_watch` runs the producer
while a background watcher reads the connection: a `cancel` (or EOF) hard-cancels
the producer and reports CANCELLED; a `health` is answered inline; normal
completion reports COMPLETED. The caller then sends the matching terminal.

Stability: Experimental.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from zygos.voice.ipc import IpcConnection

COMPLETED = "completed"
CANCELLED = "cancelled"


async def safe_send_control(conn: IpcConnection, msg: dict) -> None:
    """Send a control frame, swallowing transport errors on a closing conn."""
    try:
        await conn.send_control(msg)
    except (OSError, RuntimeError, EOFError, ConnectionError):
        pass


async def run_with_cancel_watch(
    conn: IpcConnection,
    work_factory: Callable[[asyncio.Event], Awaitable[None]],
) -> str:
    """Run work while watching `conn` for cancel. See module docstring."""
    cancel_event = asyncio.Event()

    async def watch() -> None:
        while True:
            try:
                kind, body = await conn.recv()
            except EOFError:
                cancel_event.set()
                return
            if kind != "control":
                continue
            mtype = body.get("type")
            if mtype == "cancel":
                cancel_event.set()
                return
            if mtype == "health":
                await safe_send_control(conn, {"type": "health_ok"})

    work_task = asyncio.create_task(work_factory(cancel_event))
    watch_task = asyncio.create_task(watch())
    try:
        await asyncio.wait(
            {work_task, watch_task}, return_when=asyncio.FIRST_COMPLETED)
        if cancel_event.is_set():
            # watcher tripped (cancel or EOF): stop the producer, even if it
            # also raced to completion on the same event-loop pass.
            work_task.cancel()
            await asyncio.gather(work_task, return_exceptions=True)
            # Cancel wins over normal completion, but a genuine work error that
            # raced the cancel still propagates (contract: work exceptions surface).
            if not work_task.cancelled() and work_task.exception() is not None:
                raise work_task.exception()
            return CANCELLED
        watch_task.cancel()
        await asyncio.gather(watch_task, return_exceptions=True)
        work_task.result()  # re-raise a work error to the caller
        return COMPLETED
    finally:
        # Defensive: only fires if run_with_cancel_watch itself is cancelled from
        # outside mid-await; on normal/cancel/complete paths both tasks are done.
        for task in (work_task, watch_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(work_task, watch_task, return_exceptions=True)
