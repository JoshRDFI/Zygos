"""Single-attempt four-phase tool executor with guaranteed cleanup.

The `try` starts at `prepare`, so `cleanup` runs whether or not `prepare`/`execute`/
`verify` raised (ARCHITECTURE §Tool Contract). Input validation happens BEFORE the try:
a bad-args failure owes no cleanup because no phase acquired anything.

No retry/timeout/streaming/permissions/events this cycle (M5 C2 / M8). Stability: Experimental.
"""

from __future__ import annotations

import uuid

from pydantic import ValidationError

from zygos.errors import ZygosError
from zygos.runtime.context import ExecutionContext
from zygos.tools.types import Tool, ToolCall, ToolContext, ToolResult


async def execute_tool(tool: Tool, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
    name = tool.meta.name
    call_id = call.call_id or uuid.uuid4().hex
    tctx = ToolContext(exec=ctx.child(span_id=call_id), tool=name, call_id=call_id)

    # Input validation — before the guarded block; no phase has acquired anything yet.
    try:
        input_obj = tool.meta.input_model.model_validate(call.args)
    except ValidationError as exc:
        return ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_input_invalid", error_message=str(exc)
        )

    result: ToolResult
    succeeded = False
    try:
        tool.prepare(tctx)
        output = await tool.execute(input_obj, tctx)
        verdict = tool.verify(output, tctx)
        if verdict.passed:
            result = ToolResult.succeeded(tool=name, call_id=call_id, output=output)
            succeeded = True
        else:
            result = ToolResult.failed(
                tool=name,
                call_id=call_id,
                error_code="tool_verify_failed",
                error_message=verdict.reason,
            )
    except ZygosError as exc:
        result = ToolResult.failed(
            tool=name, call_id=call_id, error_code=exc.code, error_message=str(exc)
        )
    except Exception as exc:  # noqa: BLE001 — deliberate boundary: no tool exception escapes
        result = ToolResult.failed(
            tool=name, call_id=call_id, error_code="tool_execution_failed", error_message=str(exc)
        )
    finally:
        try:
            tool.cleanup(tctx)
        except Exception as cleanup_exc:  # noqa: BLE001
            if succeeded:
                result = ToolResult.failed(
                    tool=name,
                    call_id=call_id,
                    error_code="tool_cleanup_failed",
                    error_message=str(cleanup_exc),
                )
            # else: keep the primary failure; the cleanup error is secondary.

    return result
