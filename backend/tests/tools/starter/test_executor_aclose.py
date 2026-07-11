"""M5 C3 Task 1 — _stream_with_timeout must close its inner generator promptly."""

import asyncio

import pytest

from zygos.tools.executor import _stream_with_timeout


@pytest.mark.asyncio
async def test_closes_inner_generator_on_early_aclose():
    """Closing the wrapper runs the inner generator's finally synchronously (the fix)."""
    closed = []

    async def inner():
        try:
            yield 1
            yield 2
        finally:
            closed.append(True)

    stream = _stream_with_timeout(inner(), timeout=10.0)
    first = await stream.__anext__()
    assert first == 1
    assert closed == []          # inner still suspended at `yield 1`
    await stream.aclose()        # must propagate close into the inner gen
    assert closed == [True]


@pytest.mark.asyncio
async def test_closes_inner_generator_on_deadline():
    """When the wall-clock deadline fires, the inner generator is closed."""
    closed = []

    async def inner():
        try:
            yield 1
            await asyncio.Event().wait()   # blocks past the deadline
            yield 2
        finally:
            closed.append(True)

    got = []
    stream = _stream_with_timeout(inner(), timeout=0.05)
    with pytest.raises(asyncio.TimeoutError):
        async for v in stream:
            got.append(v)
    assert got == [1]
    assert closed == [True]
