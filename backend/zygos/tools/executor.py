"""Four-phase tool executor: per-attempt timeout + guaranteed cleanup (M5 C2).

Extends the C1 single-attempt core. `_one_attempt` is the C1 guarded block plus an
`asyncio.wait_for` timeout around `execute` (the only awaitable phase). `execute_tool` wraps
`_one_attempt` in a retry loop over `tool.meta.retry.attempts` with injected backoff sleep, and
checks `ctx.cancelled` at each attempt boundary. Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from pydantic import ValidationError

from zygos.errors import ZygosError
from zygos.runtime.context import ExecutionContext
from zygos.tools.types import Tool, ToolCall, ToolChunk, ToolContext, ToolResult

DEFAULT_TIMEOUT_S = 60.0


async def _one_attempt(
    tool: Tool, input_obj, tctx: ToolContext, timeout: float
) -> tuple[ToolResult, bool, bool]:
    """One four-phase attempt. Returns (result, is_ok, retryable).

    `cleanup` always runs (finally). A cleanup raise downgrades a success to
    tool_cleanup_failed but never masks a prior failure (C1 rule).
    """
    name = tctx.tool
    call_id = tctx.call_id
    is_ok = False
    retryable = False
    result: ToolResult
    try:
        tool.prepare(tctx)
        output = await asyncio.wait_for(tool.execute(input_obj, tctx), timeout)
        verdict = tool.verify(output, tctx)
        if verdict.passed:
            result = ToolResult.succeeded(tool=name, call_id=call_id, output=output)
            is_ok = True
        else:
            result = ToolResult.failed(
                tool=name, call_id=call_id, error_code="tool_verify_failed",
                error_message=verdict.reason,
            )
    except (asyncio.TimeoutError, TimeoutError):
        result = ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_timeout",
            error_message=f"tool exceeded {timeout}s",
        )
        retryable = True
    except ZygosError as exc:
        result = ToolResult.failed(
            tool=name, call_id=call_id, error_code=exc.code, error_message=str(exc)
        )
        retryable = getattr(exc, "retryable", False)
    except Exception as exc:  # noqa: BLE001 — deliberate boundary: no tool exception escapes
        result = ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_execution_failed", error_message=str(exc)
        )
    finally:
        try:
            tool.cleanup(tctx)
        except Exception as cleanup_exc:  # noqa: BLE001
            if is_ok:
                result = ToolResult.failed(
                    tool=name, call_id=call_id, error_code="tool_cleanup_failed",
                    error_message=str(cleanup_exc),
                )
                is_ok = False
                retryable = False
            # else: keep the primary failure; the cleanup error is secondary.
    return result, is_ok, retryable


async def execute_tool(
    tool: Tool,
    call: ToolCall,
    ctx: ExecutionContext,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> ToolResult:
    name = tool.meta.name
    call_id = call.call_id or uuid.uuid4().hex
    tctx = ToolContext(exec=ctx.child(span_id=call_id), tool=name, call_id=call_id)

    # Input validation — before any attempt; no phase acquired anything yet.
    try:
        input_obj = tool.meta.input_model.model_validate(call.args)
    except ValidationError as exc:
        return ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_input_invalid", error_message=str(exc)
        )

    timeout = tool.meta.timeout_s if tool.meta.timeout_s is not None else DEFAULT_TIMEOUT_S
    retry = tool.meta.retry
    result: ToolResult = ToolResult.failed(
        tool=name, call_id=call_id, error_code="tool_error", error_message="no attempt ran"
    )
    for attempt in range(1, retry.attempts + 1):
        if ctx.cancelled:
            return ToolResult.failed(
                tool=name, call_id=call_id, error_code="tool_cancelled",
                error_message="cancelled",
            )
        result, is_ok, retryable = await _one_attempt(tool, input_obj, tctx, timeout)
        if is_ok or not retryable or attempt == retry.attempts:
            return result
        await sleep(retry.backoff_ms * (retry.multiplier ** (attempt - 1)) / 1000.0)
    return result  # unreachable: the loop always returns (attempts >= 1)


async def _stream_with_timeout(agen, timeout: float):
    """Yield from `agen` under a wall-clock total-stream deadline. Raises asyncio.TimeoutError."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    aiter = agen.__aiter__()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            value = await asyncio.wait_for(aiter.__anext__(), remaining)
        except StopAsyncIteration:
            return
        yield value


async def execute_tool_stream(
    tool: Tool,
    call: ToolCall,
    ctx: ExecutionContext,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
):
    name = tool.meta.name
    call_id = call.call_id or uuid.uuid4().hex
    tctx = ToolContext(exec=ctx.child(span_id=call_id), tool=name, call_id=call_id)

    try:
        input_obj = tool.meta.input_model.model_validate(call.args)
    except ValidationError as exc:
        yield ToolChunk(kind="result", result=ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_input_invalid", error_message=str(exc)))
        return

    timeout = tool.meta.timeout_s if tool.meta.timeout_s is not None else DEFAULT_TIMEOUT_S
    retry = tool.meta.retry

    for attempt in range(1, retry.attempts + 1):
        if ctx.cancelled:
            yield ToolChunk(kind="result", result=ToolResult.failed(
                tool=name, call_id=call_id, error_code="tool_cancelled", error_message="cancelled"))
            return

        started = False
        is_ok = False
        retryable = False
        result: ToolResult
        try:
            tool.prepare(tctx)
            last = None
            async for value in _stream_with_timeout(tool.execute_stream(input_obj, tctx), timeout):
                started = True
                last = value
                yield ToolChunk(kind="content", content=value)
            verdict = tool.verify(last, tctx)
            if verdict.passed:
                result = ToolResult.succeeded(tool=name, call_id=call_id, output=last)
                is_ok = True
            else:
                result = ToolResult.failed(
                    tool=name, call_id=call_id, error_code="tool_verify_failed",
                    error_message=verdict.reason)
        except (asyncio.TimeoutError, TimeoutError):
            result = ToolResult.failed(
                tool=name, call_id=call_id, error_code="tool_timeout",
                error_message=f"tool exceeded {timeout}s")
            retryable = True
        except ZygosError as exc:
            result = ToolResult.failed(
                tool=name, call_id=call_id, error_code=exc.code, error_message=str(exc))
            retryable = getattr(exc, "retryable", False)
        except Exception as exc:  # noqa: BLE001 — deliberate boundary
            result = ToolResult.failed(
                tool=name, call_id=call_id, error_code="tool_execution_failed",
                error_message=str(exc))
        finally:
            try:
                tool.cleanup(tctx)
            except Exception as cleanup_exc:  # noqa: BLE001
                if is_ok:
                    result = ToolResult.failed(
                        tool=name, call_id=call_id, error_code="tool_cleanup_failed",
                        error_message=str(cleanup_exc))
                    is_ok = False
                    retryable = False

        # Retry ONLY before the first chunk — identical to router.stream's `started` cutoff.
        if (not is_ok) and (not started) and retryable and attempt < retry.attempts:
            await sleep(retry.backoff_ms * (retry.multiplier ** (attempt - 1)) / 1000.0)
            continue
        yield ToolChunk(kind="result", result=result)
        return
