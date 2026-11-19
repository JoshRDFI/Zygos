"""ToolService facade — permission gate + one-level fallback over the executor (M5 C2).

Pull-only snapshot; no bus events; no bootstrap wiring (pure library). The permission check
runs ONCE per call; fallback is orchestrated here (the only layer with registry access to
resolve a fallback tool by name). Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, Literal, Sequence

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


logger = logging.getLogger(__name__)

McpDecision = Literal["allow", "deny", "not_trusted"]
McpGate = Callable[[ToolMeta], McpDecision]
McpDescribe = Callable[[ToolMeta], dict[str, Any]]


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
        mcp_gate: McpGate | None = None,
    ) -> None:
        self._registry = registry if registry is not None else ToolRegistry()
        self._policy = policy if policy is not None else PermissionPolicy()   # all-allow
        self._resolver = resolver if resolver is not None else DenyingResolver()
        self._sleep = sleep
        self._dynamic: list[str] = []
        self._mcp_gate = mcp_gate   # None: every MCP tool is "not trusted"
        self._mcp_describe: McpDescribe | None = None

    def register(self, tool: Tool) -> None:
        self._registry.register(tool)

    def set_dynamic_tools(self, tools: Sequence[Tool]) -> None:
        """Replace the previously set dynamic (e.g. MCP) tools. Built-in names win collisions."""
        for name in self._dynamic:
            self._registry.unregister(name)
        self._dynamic = []
        for tool in tools:
            name = tool.meta.name
            if self._registry.get(name) is not None:
                logger.warning("dynamic tool %r collides with an existing tool; skipped", name)
                continue
            self._registry.register(tool)
            self._dynamic.append(name)

    def bind_resolver(self, resolver: PermissionResolver) -> None:
        """Late-bind the interactive permission resolver (the server wires the WS one).

        The service is built in bootstrap with the headless DenyingResolver; the adapter
        layer binds a live resolver at wiring time (permissions.py seam).
        """
        self._resolver = resolver

    def bind_mcp_gate(self, gate: McpGate) -> None:
        """Late-bind the MCP permission decision (the supervisor is built after this service)."""
        self._mcp_gate = gate

    def bind_mcp_describe(self, describe: McpDescribe) -> None:
        """Late-bind what a permission prompt shows about an MCP tool."""
        self._mcp_describe = describe

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
                denied = (await self._check_mcp(fb.meta, fb_call, ctx, fallback=True)
                          if fb.meta.server is not None else None)
                if denied is not None:
                    yield ToolChunk(kind="result", result=denied)
                    return
                async for chunk in execute_tool_stream(fb, fb_call, ctx, sleep=self._sleep):
                    yield chunk
                return
        if terminal is not None:
            yield terminal

    async def _check_permission(
        self, tool: Tool, call: ToolCall, ctx: ExecutionContext
    ) -> ToolResult | None:
        if tool.meta.server is not None:
            return await self._check_mcp(tool.meta, call, ctx)
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

    async def _check_mcp(
        self, meta: ToolMeta, call: ToolCall, ctx: ExecutionContext, *, fallback: bool = False
    ) -> ToolResult | None:
        """MCP tools: config deny -> denied, never asked; trusted -> allowed; otherwise
        the user is asked through the permission resolver, and anything but allow refuses.

        With nobody to ask (no page connected), the resolver denies at once, so the
        refusal names the CLI way to trust the tool.

        A fallback keeps the call's id, but its prompt gets its own id, so an answer
        meant for the primary's prompt can never answer the fallback's.
        """
        decision: McpDecision = "deny"
        if self._mcp_gate is None:
            decision = "not_trusted"
        else:
            try:
                decision = self._mcp_gate(meta)
            except Exception:  # noqa: BLE001 - a broken gate must refuse, never allow or ask
                logger.exception("mcp permission gate failed for %r; refusing", meta.name)
        if decision == "allow":
            return None
        if decision == "not_trusted":
            details: dict[str, Any] = {}
            if self._mcp_describe is not None:
                try:
                    described = self._mcp_describe(meta)
                    details = described if isinstance(described, dict) else {}
                except Exception as exc:  # noqa: BLE001 - the prompt still asks, just with less
                    logger.warning("mcp describe failed for %r (%s)", meta.name, type(exc).__name__)
            tctx = ToolContext(
                exec=ctx.child(span_id=call.call_id), tool=meta.name, call_id=call.call_id
            )
            prompt_id = f"{call.call_id}:fb" if fallback else call.call_id
            req = PermissionRequest(
                tool=meta.name, args_summary=call.args,
                run_id=ctx.run_id, call_id=prompt_id, details=details,
            )
            if await self._resolver.resolve(req, tctx) == "allow":
                return None
            message = (
                "not trusted — answer the prompt in the web page, or run: "
                f"zygos mcp trust {meta.server}/{meta.server_tool}"
            )
        else:
            message = "permission denied"
        return ToolResult.failed(
            tool=meta.name, call_id=call.call_id,
            error_code="tool_permission_denied", error_message=message,
        )

    async def _run_with_fallback(
        self, tool: Tool, call: ToolCall, ctx: ExecutionContext, depth: int
    ) -> ToolResult:
        """Run `tool`, recursing one level into its fallback on failure.

        NOTE: a built-in fallback is intentionally NOT re-gated through the permission
        check — the primary's gate covers the call (spec §7, maintainer-approved). A
        fallback configured with `permission="deny"`/`"ask"` is a config smell that
        would surface in review, not something this layer defends against. An MCP
        fallback (``meta.server`` set) is gated like any MCP call: trust is per tool.
        """
        result = await execute_tool(tool, call, ctx, sleep=self._sleep)
        if result.ok or depth == 1 or not tool.meta.fallback:
            return result
        fb = self._registry.get(tool.meta.fallback)
        if fb is None:
            return result   # missing fallback: primary failure stands
        fb_call = call.model_copy(update={"tool": fb.meta.name})   # keep call_id for correlation
        if fb.meta.server is not None and (denied := await self._check_mcp(fb.meta, fb_call, ctx, fallback=True)) is not None:
            return denied
        return await self._run_with_fallback(fb, fb_call, ctx, depth=1)   # one level only

    def snapshot(self) -> ToolServiceSnapshot:
        return ToolServiceSnapshot(registered=self._registry.list())
