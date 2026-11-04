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

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.agent.loop import run_agentic_loop
from zygos.agent.observer import ToolCallFinished, ToolCallStarted, ToolEvent
from zygos.api.frames import CHAT, TOOLS, Frame
from zygos.api.modality import TurnModality, render_modality
from zygos.api.session import Session
from zygos.api.speech import speak_reply
from zygos.api.thinking import THINKING_PREFIX, resolve_think, schedule_think_state
from zygos.api.voice_gate import VoiceGate
from zygos.memory.service import MemoryService
from zygos.personalization import Personalization, PreferencesStore
from zygos.personalization.render import render_identity
from zygos.providers.types import GenerationRequest, Message
from zygos.reasoning.service import ReasoningService
from zygos.reasoning.types import ReasoningInput
from zygos.runtime.context import CancelToken
from zygos.services.model import ModelService
from zygos.thinking.capture import TailBuffer, ThinkingRecorder
from zygos.thinking.support import ThinkingSupportChecker
from zygos.tools.service import ToolService
from zygos.tools.types import Tool
from zygos.voice import VoiceService

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
    voice_service: "VoiceService | None" = None
    voice_gate: "VoiceGate | None" = None
    duck_gain: float = 0.2
    duck_timeout_s: float = 2.0
    preferences: PreferencesStore | None = None
    # RFC-0012: configured thinking default (providers.think) and support gate
    think_default: bool | None = False
    thinking_support: ThinkingSupportChecker | None = None


def _json_safe(value):
    """Render a tool output for a JSON frame payload."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)


def system_texts(modality: TurnModality,
                 prefs: Personalization = Personalization()) -> tuple[str, ...]:
    """Runtime-authored system messages for this turn, ahead of memory (RFC-0010 §3, §3a).

    Identity first, then modality.

    One rendering site shared by the message-list paths and the reasoning path.
    """
    texts = (render_identity(prefs), render_modality(modality))
    return tuple(t for t in texts if t)


def build_messages(context: tuple[str, ...], text: str,
                   modality: TurnModality = TurnModality(),
                   prefs: Personalization = Personalization()) -> tuple[Message, ...]:
    messages: list[Message] = [Message(role="system", content=t)
                               for t in system_texts(modality, prefs)]
    if context:
        joined = "\n".join(context)
        messages.append(Message(role="system", content=f"Relevant memory:\n{joined}"))
    messages.append(Message(role="user", content=text))
    return tuple(messages)


def format_exchange(user_text: str, assistant_text: str) -> str:
    return f"User: {user_text}\nAssistant: {assistant_text}"


def _speaks_reply(session: Session, deps: TurnDeps) -> bool:
    """Whether this turn's reply will be synthesized (the gate before speak_reply)."""
    return bool(session.speak and deps.voice_service is not None
                and deps.voice_service.tts_available)


async def run_turn(session: Session, deps: TurnDeps, text: str, cancel: CancelToken,
                   *, spoken_input: bool, think: bool | None,
                   rethink_of: str | None = None) -> None:
    turn_id = deps.new_id()
    session.last_user_text = text
    session.last_turn_id = turn_id
    speaks = _speaks_reply(session, deps)
    modality = TurnModality(spoken_input=spoken_input, spoken_output=speaks)
    prefs = Personalization()
    if deps.preferences is not None:
        try:
            prefs = deps.preferences.get()
        except Exception:  # noqa: BLE001 - personalization is advisory (RFC-0010)
            logger.warning("preferences read failed; degrading to no identity", exc_info=True)
    effective, unsupported_reason = await resolve_think(session, deps, think)
    recorder = ThinkingRecorder(turn_id)
    ctx = session.root.child(turn_id, cancel=cancel)
    session.begin_turn()
    session.enqueue(Frame(channel=CHAT, type="turn.start", payload={
        "turn_id": turn_id, "think": effective, "rethink_of": rethink_of}))

    def _think_fields() -> dict:
        return {"think": effective, "thinking_ms": recorder.total_ms,
                "think_unsupported_reason": unsupported_reason, "rethink_of": rethink_of}

    final = ""
    end_extra: dict = {}
    prefix: asyncio.Task | None = None
    try:
        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": "", "cancelled": True, **_think_fields()}))
            return

        if spoken_input and effective is True and speaks:
            prefix = asyncio.create_task(
                speak_reply(session, deps.voice_service, ctx, THINKING_PREFIX, turn_id))

        context: tuple[str, ...] = ()
        if deps.memory_service is not None:
            try:
                records = await deps.memory_service.retrieve(ctx, query=text)
                context = tuple(r.content.text for r in records)
            except Exception:  # noqa: BLE001 - retrieval is advisory (RFC-0006)
                logger.warning("memory retrieve failed; degrading to no context", exc_info=True)
                context = ()

        if deps.tools:
            messages = build_messages(context, text, modality, prefs)

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
                tools=deps.tools, messages=messages, config=deps.tool_loop_config, observer=_frame,
                think=effective, thinking=recorder)
            final = agent_result.text
            end_extra = {"stop_reason": agent_result.stop_reason, "iterations": agent_result.iterations}
        elif not deps.reasoning_enabled:
            request = GenerationRequest(messages=build_messages(context, text, modality, prefs),
                                        think=effective)
            thinking = TailBuffer()  # bounded, filled chunk by chunk (RFC-0012 §6)
            started = time.monotonic()
            first_text_at: float | None = None
            async for chunk in deps.model_service.stream(ctx, request):
                if chunk.thinking:
                    thinking.append(chunk.thinking)
                if ctx.cancelled:
                    break
                if chunk.text:
                    if first_text_at is None:
                        first_text_at = time.monotonic()
                    final += chunk.text
                    session.enqueue(Frame(channel=CHAT, type="token", payload={"text": chunk.text}))
            ended = first_text_at if first_text_at is not None else time.monotonic()
            await recorder.record(ctx, step="direct", index=0, text=thinking,
                                  elapsed_ms=int((ended - started) * 1000))
        else:
            reasoning = deps.reasoning_factory()
            result = await reasoning.run(ctx, ReasoningInput(
                prompt=text, context=context, system=system_texts(modality, prefs),
                think=effective), thinking=recorder)
            final = result.text
            end_extra = {
                "confidence": result.final_confidence,
                "loops": result.loops_used,
                "halted_early": result.halted_early,
                "model": result.model,
            }

        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": final, "cancelled": True, **_think_fields()}))
            return

        if deps.memory_service is not None:
            deps.memory_service.store(ctx, text=format_exchange(text, final))

        payload = {"text": final, **end_extra, **_think_fields()}
        session.enqueue(Frame(channel=CHAT, type="turn.end", payload=payload))

        if prefix is not None:
            await prefix
        if _speaks_reply(session, deps) and final and not ctx.cancelled:
            await speak_reply(session, deps.voice_service, ctx, final, turn_id)
    except Exception:  # noqa: BLE001 - a failed turn must not kill the session
        logger.exception("turn failed")
        session.enqueue(Frame(channel=CHAT, type="error", payload={"message": "generation failed"}))
    finally:
        if prefix is not None:
            if not prefix.done():
                prefix.cancel()
            await asyncio.gather(prefix, return_exceptions=True)
        session.end_turn()
        # RFC-0012 §2: a support change (e.g. Ollama warmed up since connect) is
        # re-announced. Backgrounded: barge-in awaits this task, and a cold probe
        # can take PROBE_TIMEOUT_S. Normally a cache hit, sending nothing.
        if getattr(deps, "thinking_support", None) is not None and session.connected:
            schedule_think_state(session, deps, only_if_changed=True)
