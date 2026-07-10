"""ToolService facade — permission gate + one-level fallback over the executor (M5 C2).

Pull-only snapshot; no bus events; no bootstrap wiring (pure library). The permission check
runs ONCE per call; fallback is orchestrated here (the only layer with registry access to
resolve a fallback tool by name). Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncIterator, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from zygos.errors import ToolNotFound
from zygos.runtime.context import ExecutionContext
from zygos.tools.executor import execute_tool, execute_tool_stream
from zygos.tools.permissions import (
    DenyingResolver,
    PermissionPolicy,
    PermissionRequest,
    PermissionResolver,
)
from zygos.tools.registry import ToolRegistry
from zygos.tools.types import Tool, ToolCall, ToolChunk, ToolContext, ToolMeta, ToolResult


class ToolServiceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    registered: list[ToolMeta]


def _ensure_call_id(call: ToolCall) -> ToolCall:
    """Fill call_id once so the resolver and executor share one id."""
    if call.call_id is not None:
        return call
    return call.model_copy(update={"call_id": uuid.uuid4().hex})


class ToolService:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        *,
        policy: PermissionPolicy | None = None,
        resolver: PermissionResolver | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._registry = registry if registry is not None else ToolRegistry()
        self._policy = policy if policy is not None else PermissionPolicy()   # all-allow
        self._resolver = resolver if resolver is not None else DenyingResolver()
        self._sleep = sleep

    def register(self, tool: Tool) -> None:
        self._registry.register(tool)

    async def execute(self, call: ToolCall, ctx: ExecutionContext) -> ToolResult:
        tool = self._registry.get(call.tool)
        if tool is None:
            raise ToolNotFound(f"unknown tool: {call.tool!r}")
        call = _ensure_call_id(call)
        denied = await self._check_permission(tool, call, ctx)
        if denied is not None:
            return denied
        return await self._run_with_fallback(tool, call, ctx, depth=0)

    async def execute_stream(
        self, call: ToolCall, ctx: ExecutionContext
    ) -> AsyncIterator[ToolChunk]:
        tool = self._registry.get(call.tool)
        if tool is None:
            raise ToolNotFound(f"unknown tool: {call.tool!r}")
        call = _ensure_call_id(call)
        denied = await self._check_permission(tool, call, ctx)
        if denied is not None:
            yield ToolChunk(kind="result", result=denied)
            return

        started = False
        terminal: ToolChunk | None = None
        async for chunk in execute_tool_stream(tool, call, ctx, sleep=self._sleep):
            if chunk.kind == "content":
                started = True
                yield chunk
            else:
                terminal = chunk

        # Primary succeeded, or already streamed content -> its terminal stands.
        if terminal is not None and terminal.result is not None and terminal.result.ok:
            yield terminal
            return
        if (not started) and tool.meta.fallback:
            fb = self._registry.get(tool.meta.fallback)
            if fb is not None:
                fb_call = call.model_copy(update={"tool": fb.meta.name})
                async for chunk in execute_tool_stream(fb, fb_call, ctx, sleep=self._sleep):
                    yield chunk
                return
        if terminal is not None:
            yield terminal

    async def _check_permission(
        self, tool: Tool, call: ToolCall, ctx: ExecutionContext
    ) -> ToolResult | None:
        decision = self._policy.decide(tool.meta)
        if decision == "ask":
            tctx = ToolContext(
                exec=ctx.child(span_id=call.call_id), tool=tool.meta.name, call_id=call.call_id
            )
            req = PermissionRequest(
                tool=tool.meta.name, args_summary=call.args,
                run_id=ctx.run_id, call_id=call.call_id,
            )
            decision = await self._resolver.resolve(req, tctx)
        if decision == "allow":
            return None
        return ToolResult.failed(
            tool=tool.meta.name, call_id=call.call_id,
            error_code="tool_permission_denied", error_message="permission denied",
        )

    async def _run_with_fallback(
        self, tool: Tool, call: ToolCall, ctx: ExecutionContext, depth: int
    ) -> ToolResult:
        result = await execute_tool(tool, call, ctx, sleep=self._sleep)
        if result.ok or depth == 1 or not tool.meta.fallback:
            return result
        fb = self._registry.get(tool.meta.fallback)
        if fb is None:
            return result   # missing fallback: primary failure stands
        fb_call = call.model_copy(update={"tool": fb.meta.name})   # keep call_id for correlation
        return await self._run_with_fallback(fb, fb_call, ctx, depth=1)   # one level only

    def snapshot(self) -> ToolServiceSnapshot:
        return ToolServiceSnapshot(registered=self._registry.list())
