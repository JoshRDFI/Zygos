"""The single-thread inference executor must serialize work even when a prior
call's awaiting coroutine was cancelled (orphaned thread still running)."""
from __future__ import annotations

import asyncio
import threading

from zygos.voice.sidecar.inference import new_inference_executor, run_inference


async def test_single_thread_executor_serializes_across_cancellation():
    executor = new_inference_executor()
    started: list[str] = []
    finished: list[str] = []
    gate = threading.Event()

    def blocking(tag: str) -> str:
        started.append(tag)
        if tag == "first":
            gate.wait(2.0)  # hold the one worker thread until released
        finished.append(tag)
        return tag

    try:
        # Start the first inference, then cancel its awaiter: the thread is
        # orphaned but keeps running on the executor's single worker.
        t1 = asyncio.create_task(run_inference(executor, blocking, "first"))
        await asyncio.sleep(0.05)
        assert started == ["first"]
        t1.cancel()
        try:
            await t1
        except asyncio.CancelledError:
            pass

        # The next inference must NOT begin until the orphaned first finishes.
        t2 = asyncio.create_task(run_inference(executor, blocking, "second"))
        await asyncio.sleep(0.05)
        assert started == ["first"]  # second is queued behind the orphan, not running

        gate.set()  # let the orphan finish; the queued second then runs
        assert await t2 == "second"
        assert finished == ["first", "second"]  # strictly serialized
    finally:
        gate.set()
        executor.shutdown(wait=False)
