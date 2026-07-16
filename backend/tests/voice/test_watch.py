"""Unit tests for the shared cancel-watch worker primitive."""
from __future__ import annotations

import asyncio

from zygos.voice.ipc import connect, listen
from zygos.voice.sidecar.watch import (
    CANCELLED,
    COMPLETED,
    run_with_cancel_watch,
    safe_send_control,
)


async def _pair():
    listener = await listen()
    client = await connect(listener.address)
    server = await listener.accept()
    return listener, server, client


async def test_completes_when_work_finishes():
    listener, server, client = await _pair()
    try:
        sent = []

        async def work(cancel_event):
            for i in range(3):
                await server.send_pcm(bytes([i]))
                sent.append(i)

        outcome = await run_with_cancel_watch(server, work)
        assert outcome == COMPLETED
        assert sent == [0, 1, 2]
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_cancelled_when_client_sends_cancel():
    listener, server, client = await _pair()
    try:
        started = asyncio.Event()

        async def work(cancel_event):
            started.set()
            await cancel_event.wait()  # graceful stop point

        task = asyncio.create_task(run_with_cancel_watch(server, work))
        await started.wait()
        await client.send_control({"type": "cancel"})
        assert await task == CANCELLED
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_health_is_answered_inline_during_work():
    listener, server, client = await _pair()
    try:
        release = asyncio.Event()

        async def work(cancel_event):
            await release.wait()

        task = asyncio.create_task(run_with_cancel_watch(server, work))
        await client.send_control({"type": "health"})
        kind, body = await client.recv()
        assert kind == "control" and body == {"type": "health_ok"}
        release.set()
        assert await task == COMPLETED
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_eof_is_treated_as_cancelled():
    listener, server, client = await _pair()
    try:
        async def work(cancel_event):
            await cancel_event.wait()

        task = asyncio.create_task(run_with_cancel_watch(server, work))
        await asyncio.sleep(0)
        await client.close()  # EOF to the watcher
        assert await task == CANCELLED
    finally:
        await server.close()
        await listener.close()


async def test_work_exception_propagates():
    listener, server, client = await _pair()
    try:
        async def work(cancel_event):
            raise ValueError("boom")

        try:
            await run_with_cancel_watch(server, work)
            assert False, "expected ValueError"
        except ValueError as exc:
            assert str(exc) == "boom"
    finally:
        await client.close()
        await server.close()
        await listener.close()


async def test_work_exception_propagates_even_when_cancel_races():
    listener, server, client = await _pair()
    try:
        async def work(cancel_event):
            await cancel_event.wait()
            raise ValueError("cleanup-boom")

        task = asyncio.create_task(run_with_cancel_watch(server, work))
        await asyncio.sleep(0)
        await client.send_control({"type": "cancel"})
        try:
            await task
            assert False, "expected ValueError"
        except ValueError as exc:
            assert str(exc) == "cleanup-boom"
    finally:
        await client.close()
        await server.close()
        await listener.close()
