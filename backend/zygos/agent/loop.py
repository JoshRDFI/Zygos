"""The agentic loop (RFC-0008 §4-§6): generate-with-tools -> dispatch -> feed back -> repeat.

Wraps the model-interaction step. Native thinking + tool-calling happen together, on
every turn, independent of the RDT reasoning-orchestration gate. The ToolInvocation ->
ToolCall mapping lives here (the composition layer), keeping providers/ free of tools/.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.agent.observer import ToolCallFinished, ToolCallStarted, ToolObserver
from zygos.agent.schema import tool_schema
from zygos.errors import ToolNotFound
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService, TurnRoute
from zygos.services.router import RouteChoice
from zygos.thinking.capture import ThinkingRecorder
from zygos.tools.service import ToolService
from zygos.tools.types import Tool, ToolCall, ToolResult


# A tool called with the same arguments this many times in one turn gets a note
# appended to that call's tool message. It never blocks the call.
REPEAT_NUDGE_AT = (3, 5, 8)


@dataclass(frozen=True)
class AgentResult:
    text: str
    messages: tuple[Message, ...]
    iterations: int
    stop_reason: Literal["stop", "max_iterations", "cancelled"]


def _render(result: ToolResult) -> str:
    """Render a ToolResult as the content of a "tool" message (RFC-0008 §5)."""
    if not result.ok:
        return json.dumps({"error": result.error_code, "message": result.error_message})
    out = result.output
    if isinstance(out, BaseModel):
        return out.model_dump_json()
    try:
        return json.dumps(out)
    except TypeError:
        return json.dumps(str(out))


async def run_agentic_loop(
    ctx: ExecutionContext,
    *,
    model_service: ModelService,
    tool_service: ToolService,
    tools: Sequence[Tool],
    messages: Sequence[Message],
    config: ToolLoopConfig,
    observer: ToolObserver | None = None,
    think: bool | None = None,
    thinking: ThinkingRecorder | None = None,
    route: TurnRoute | None = None,
    on_route: Callable[[RouteChoice], None] | None = None,
    on_loading: Callable[[RouteChoice], None] | None = None,
) -> AgentResult:
    """``route`` is the turn's pinned route (RFC-0013 §5), passed to every
    generation with ``on_route``/``on_loading``. CONFIG_ORDER keeps the
    router's configured order; None looks the default up per call."""
    routing = {"route": route, "on_route": on_route, "on_loading": on_loading}
    schemas = tuple(tool_schema(t) for t in tools)
    history: list[Message] = list(messages)
    seen: dict[tuple[str, str], int] = {}

    for i in range(config.max_iterations):
        if ctx.cancelled:
            return AgentResult(text="", messages=tuple(history), iterations=i, stop_reason="cancelled")

        request = GenerationRequest(messages=tuple(history), tools=schemas,
                                    tool_choice=config.default_tool_choice, think=think)
        t0 = time.monotonic()
        result = await model_service.generate(ctx, request, **routing)
        if thinking is not None:
            await thinking.record(ctx, step="tool_loop", index=i, text=result.thinking,
                                  elapsed_ms=int((time.monotonic() - t0) * 1000))

        if not result.tool_calls:
            return AgentResult(text=result.text, messages=tuple(history),
                               iterations=i + 1, stop_reason="stop")

        history.append(Message(role="assistant", content=result.text, tool_calls=result.tool_calls))

        if ctx.cancelled:
            return AgentResult(text="", messages=tuple(history), iterations=i + 1, stop_reason="cancelled")

        async def _dispatch(inv):
            if observer is not None:
                observer(ToolCallStarted(call_id=inv.id, name=inv.name, arguments=dict(inv.arguments)))
            try:
                res = await tool_service.execute(
                    ToolCall(tool=inv.name, args=inv.arguments, call_id=inv.id),
                    ctx.child(inv.id),
                )
            except ToolNotFound as exc:
                res = ToolResult.failed(
                    tool=inv.name, call_id=inv.id,
                    error_code="tool_not_found", error_message=str(exc),
                )
            if observer is not None:
                observer(ToolCallFinished(call_id=inv.id, name=inv.name, result=res))
            return res

        results = await asyncio.gather(*[_dispatch(inv) for inv in result.tool_calls])
        for inv, res in zip(result.tool_calls, results):
            content = _render(res)
            key = (inv.name, json.dumps(inv.arguments, sort_keys=True, default=str))
            seen[key] = n = seen.get(key, 0) + 1
            if n in REPEAT_NUDGE_AT:
                content += (f"\n\nNote from Zygos: this is call {n} to {inv.name} with the "
                            "same arguments in this turn. Look at the earlier results and "
                            "try a different approach, or answer with what you have.")
            history.append(Message(role="tool", tool_call_id=inv.id, content=content))

    # Iteration cap reached with tool calls still pending: one final tool-free answer.
    final_req = GenerationRequest(messages=tuple(history), tools=schemas, tool_choice="none",
                                 think=think)
    t0 = time.monotonic()
    final = await model_service.generate(ctx, final_req, **routing)
    if thinking is not None:
        await thinking.record(ctx, step="tool_loop", index=config.max_iterations, text=final.thinking,
                              elapsed_ms=int((time.monotonic() - t0) * 1000))
    return AgentResult(text=final.text, messages=tuple(history),
                       iterations=config.max_iterations, stop_reason="max_iterations")
