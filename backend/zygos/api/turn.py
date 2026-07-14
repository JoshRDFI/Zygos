"""The chat turn loop (RFC-0007 §5): retrieve → generate → record → finish.

Produces chat frames directly onto the session's outbound queue — never through
the event bus (output is load-bearing, not observational; RFC-0002). Memory is
guarded by presence and advisory (a retrieve failure degrades, never aborts).
Reasoning-off streams tokens; reasoning-on constructs a fresh ReasoningService
per turn and delivers the answer at turn.end. Tools-present (deps.tools non-empty)
wins over both: it drives the agentic loop (RFC-0008), emitting live `tools:call`/
`tools:result` frames and delivering the answer whole at turn.end (no chat:token
frames — the no-synthetic-tokens rule).

Stability: Experimental.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.agent.loop import run_agentic_loop
from zygos.agent.observer import ToolCallFinished, ToolCallStarted, ToolEvent
from zygos.api.frames import CHAT, TOOLS, Frame
from zygos.api.session import Session
from zygos.memory.service import MemoryService
from zygos.providers.types import GenerationRequest, Message
from zygos.reasoning.service import ReasoningService
from zygos.reasoning.types import ReasoningInput
from zygos.runtime.context import CancelToken
from zygos.services.model import ModelService
from zygos.tools.service import ToolService
from zygos.tools.types import Tool

logger = logging.getLogger("zygos.api.turn")


@dataclass(frozen=True)
class TurnDeps:
    model_service: ModelService
    reasoning_factory: Callable[[], ReasoningService]
    reasoning_enabled: bool
    memory_service: MemoryService | None
    new_id: Callable[[], str]
    tool_service: ToolService | None = None
    tools: tuple[Tool, ...] = ()
    tool_loop_config: ToolLoopConfig | None = None


def _json_safe(value):
    """Render a tool output for a JSON frame payload."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)


def build_messages(context: tuple[str, ...], text: str) -> tuple[Message, ...]:
    messages: list[Message] = []
    if context:
        joined = "\n".join(context)
        messages.append(Message(role="system", content=f"Relevant memory:\n{joined}"))
    messages.append(Message(role="user", content=text))
    return tuple(messages)


def format_exchange(user_text: str, assistant_text: str) -> str:
    return f"User: {user_text}\nAssistant: {assistant_text}"


async def run_turn(session: Session, deps: TurnDeps, text: str, cancel: CancelToken) -> None:
    turn_id = deps.new_id()
    ctx = session.root.child(turn_id, cancel=cancel)
    session.begin_turn()
    session.enqueue(Frame(channel=CHAT, type="turn.start", payload={"turn_id": turn_id}))
    final = ""
    end_extra: dict = {}
    try:
        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": "", "cancelled": True}))
            return

        context: tuple[str, ...] = ()
        if deps.memory_service is not None:
            try:
                records = await deps.memory_service.retrieve(ctx, query=text)
                context = tuple(r.content.text for r in records)
            except Exception:  # noqa: BLE001 - retrieval is advisory (RFC-0006)
                logger.warning("memory retrieve failed; degrading to no context", exc_info=True)
                context = ()

        if deps.tools:
            messages = build_messages(context, text)

            def _frame(event: ToolEvent) -> None:
                if isinstance(event, ToolCallStarted):
                    session.enqueue(Frame(channel=TOOLS, type="call", payload={
                        "call_id": event.call_id, "tool": event.name,
                        "arguments": dict(event.arguments)}))
                else:  # ToolCallFinished
                    r = event.result
                    payload = {"call_id": event.call_id, "tool": event.name, "ok": r.ok}
                    if r.ok:
                        payload["output"] = _json_safe(r.output)
                    else:
                        payload["error_code"] = r.error_code
                        payload["error_message"] = r.error_message
                    session.enqueue(Frame(channel=TOOLS, type="result", payload=payload))

            agent_result = await run_agentic_loop(
                ctx, model_service=deps.model_service, tool_service=deps.tool_service,
                tools=deps.tools, messages=messages, config=deps.tool_loop_config, observer=_frame)
            final = agent_result.text
            end_extra = {"stop_reason": agent_result.stop_reason, "iterations": agent_result.iterations}
        elif not deps.reasoning_enabled:
            request = GenerationRequest(messages=build_messages(context, text))
            async for chunk in deps.model_service.stream(ctx, request):
                if ctx.cancelled:
                    break
                if chunk.text:
                    final += chunk.text
                    session.enqueue(Frame(channel=CHAT, type="token", payload={"text": chunk.text}))
        else:
            reasoning = deps.reasoning_factory()
            result = await reasoning.run(ctx, ReasoningInput(prompt=text, context=context))
            final = result.text
            end_extra = {
                "confidence": result.final_confidence,
                "loops": result.loops_used,
                "halted_early": result.halted_early,
                "model": result.model,
            }

        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": final, "cancelled": True}))
            return

        if deps.memory_service is not None:
            deps.memory_service.store(ctx, text=format_exchange(text, final))

        payload = {"text": final, **end_extra}
        session.enqueue(Frame(channel=CHAT, type="turn.end", payload=payload))
    except Exception:  # noqa: BLE001 - a failed turn must not kill the session
        logger.exception("turn failed")
        session.enqueue(Frame(channel=CHAT, type="error", payload={"message": "generation failed"}))
    finally:
        session.end_turn()
