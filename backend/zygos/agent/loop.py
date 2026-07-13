"""The agentic loop (RFC-0008 §4-§6): generate-with-tools -> dispatch -> feed back -> repeat.

Wraps the model-interaction step. Native thinking + tool-calling happen together, on
every turn, independent of the RDT reasoning-orchestration gate. The ToolInvocation ->
ToolCall mapping lives here (the composition layer), keeping providers/ free of tools/.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.agent.schema import tool_schema
from zygos.errors import ToolNotFound
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService
from zygos.tools.service import ToolService
from zygos.tools.types import Tool, ToolCall, ToolResult


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
) -> AgentResult:
    schemas = tuple(tool_schema(t) for t in tools)
    history: list[Message] = list(messages)

    for i in range(config.max_iterations):
        if ctx.cancelled:
            return AgentResult(text="", messages=tuple(history), iterations=i, stop_reason="cancelled")

        request = GenerationRequest(messages=tuple(history), tools=schemas,
                                    tool_choice=config.default_tool_choice)
        result = await model_service.generate(ctx, request)

        if not result.tool_calls:
            return AgentResult(text=result.text, messages=tuple(history),
                               iterations=i + 1, stop_reason="stop")

        history.append(Message(role="assistant", content=result.text, tool_calls=result.tool_calls))

        if ctx.cancelled:
            return AgentResult(text="", messages=tuple(history), iterations=i + 1, stop_reason="cancelled")

        async def _dispatch(inv):
            try:
                return await tool_service.execute(
                    ToolCall(tool=inv.name, args=inv.arguments, call_id=inv.id),
                    ctx.child(inv.id),
                )
            except ToolNotFound as exc:
                return ToolResult.failed(
                    tool=inv.name, call_id=inv.id,
                    error_code="tool_not_found", error_message=str(exc),
                )

        results = await asyncio.gather(*[_dispatch(inv) for inv in result.tool_calls])
        for inv, res in zip(result.tool_calls, results):
            history.append(Message(role="tool", tool_call_id=inv.id, content=_render(res)))

    # Iteration cap reached with tool calls still pending: one final tool-free answer.
    final_req = GenerationRequest(messages=tuple(history), tools=schemas, tool_choice="none")
    final = await model_service.generate(ctx, final_req)
    return AgentResult(text=final.text, messages=tuple(history),
                       iterations=config.max_iterations, stop_reason="max_iterations")
