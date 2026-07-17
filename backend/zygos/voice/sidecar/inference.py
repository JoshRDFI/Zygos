"""Serialized inference execution for real sidecar workers.

Real inference (transcribe/synthesize) runs on a DEDICATED single-thread
executor per worker. A barge-in cancels the awaiting coroutine but cannot stop
the underlying thread, so the inference is orphaned and keeps running on the
shared model object. A max_workers=1 executor guarantees the orphan finishes
before the next utterance's inference starts — the next submission queues behind
it on the one thread — so no two inference calls ever touch one model object
concurrently (WhisperModel / Kokoro are not concurrency-safe). Cancellation
stays prompt: only the NEXT inference waits; the `cancelled` terminal is emitted
immediately by the worker's coroutine layer.

Stability: Experimental.
"""
from __future__ import annotations

import asyncio
import concurrent.futures


def new_inference_executor() -> concurrent.futures.ThreadPoolExecutor:
    """A dedicated single-thread pool that serializes all inference for one worker."""
    return concurrent.futures.ThreadPoolExecutor(max_workers=1)


async def run_inference(executor: concurrent.futures.ThreadPoolExecutor, fn, *args):
    """Run blocking `fn(*args)` on `executor`. With a single-thread executor, a
    still-running orphaned prior call blocks this one from starting until it
    finishes — no concurrent inference on the shared model."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, fn, *args)
