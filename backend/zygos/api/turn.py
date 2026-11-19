"""The chat turn loop (RFC-0007 §5): retrieve → generate → record → finish.

Produces chat frames directly onto the session's outbound queue — never through
the event bus (output is load-bearing, not observational; RFC-0002). Memory is
guarded by presence and advisory (a retrieve failure degrades, never aborts).
Reasoning-off streams tokens (with the speaker on, speaking them sentence by sentence
as they arrive); reasoning-on constructs a fresh ReasoningService
per turn and delivers the answer at turn.end. Tools-present (this turn's tool set non-empty)
wins over both: it drives the agentic loop (RFC-0008), emitting live `tools:call`/
`tools:result` frames (with ``server`` for an MCP tool) and delivering the answer whole
at turn.end (no chat:token frames — the no-synthetic-tokens rule).

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging
import time
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from zygos.agent.config import ToolLoopConfig
from zygos.agent.loop import run_agentic_loop
from zygos.agent.observer import ToolCallFinished, ToolCallStarted, ToolEvent
from zygos.api.frames import CHAT, TOOLS, Frame
from zygos.api.modality import TurnModality, render_modality
from zygos.api.session import Session
from zygos.api.speech import speak_reply
from zygos.api.speech_stream import SpeechPacer, StreamingSpeaker
from zygos.api.thinking import THINKING_PREFIX, resolve_think, schedule_think_state
from zygos.api.voice_gate import VoiceGate
from zygos.memory.service import MemoryService
from zygos.personalization import Personalization, PreferencesStore
from zygos.personalization.render import render_identity
from zygos.providers.types import GenerationRequest, Message
from zygos.reasoning.service import ReasoningService
from zygos.reasoning.types import ReasoningInput
from zygos.runtime.context import CancelToken, ExecutionContext
from zygos.runtime.events import ModelChosen
from zygos.services.model import CATEGORY_OF, CONFIG_ORDER, ModelService, classify_task
from zygos.services.router import RouteChoice
from zygos.thinking.capture import TailBuffer, ThinkingRecorder
from zygos.thinking.support import ThinkingSupportChecker
from zygos.tools.service import ToolService
from zygos.tools.types import Tool
from zygos.voice import VoiceService

if TYPE_CHECKING:
    from zygos.models.default import DefaultStatus

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
    # The tools for one turn (built-ins + the MCP tools offered now); read once per turn,
    # inside its loop. None: ``tools``.
    tools_for_turn: Callable[[], tuple[Tool, ...]] | None = None
    tool_loop_config: ToolLoopConfig | None = None
    voice_service: "VoiceService | None" = None
    voice_gate: "VoiceGate | None" = None
    duck_gain: float = 0.2
    duck_timeout_s: float = 2.0
    preferences: PreferencesStore | None = None
    # RFC-0012: configured thinking default (providers.think) and support gate
    think_default: bool | None = False
    thinking_support: ThinkingSupportChecker | None = None
    # RFC-0013 §5: the runtime's default-model status, for the model.chosen reason
    default_status: "Callable[[], DefaultStatus] | None" = None


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


def _route_dict(route: RouteChoice | None) -> dict | None:
    return None if route is None else {"provider": route.provider, "model": route.model}


async def _emit_model_chosen(ctx: ExecutionContext, deps: TurnDeps, turn_id: str,
                             category: str, pinned: RouteChoice | None) -> None:
    """One ``model.chosen`` trace per turn (RFC-0013 §11). Observational: a failure
    to work out the reason never touches the turn."""
    try:
        if pinned is not None:
            route, reason = pinned, "saved default"
        else:
            status = deps.default_status() if deps.default_status is not None else None
            if status is not None and status.ignored is not None:
                reason = f"saved default ignored: {status.reason}"
            else:
                reason = "config default"
            if status is not None and status.source == "config":
                route = status.route
            else:
                route = deps.model_service.select_model(route=CONFIG_ORDER)
        await ctx.emit(ModelChosen(turn_id=turn_id, category=category, provider=route.provider,
                                   model=route.model, reason=reason), source="turn")
    except Exception:  # noqa: BLE001 - trace only
        logger.warning("model.chosen trace failed", exc_info=True)


# tools_for_turn callables failing right now: warned once, quiet until they recover.
_FAILING_TOOL_SETS: "weakref.WeakSet[Callable[[], tuple[Tool, ...]]]" = weakref.WeakSet()


def _turn_tools(deps: TurnDeps) -> tuple[Tool, ...]:
    """This turn's tools. A failure to work out the MCP part leaves the built-ins."""
    source = deps.tools_for_turn
    if source is None:
        return deps.tools
    try:
        tools = source()
    except Exception:  # noqa: BLE001 - MCP is optional; the turn goes on without it
        if source in _FAILING_TOOL_SETS:
            logger.debug("per-turn tool set still failing; using the built-in tools")
        else:
            _FAILING_TOOL_SETS.add(source)
            logger.warning("per-turn tool set failed; using the built-in tools", exc_info=True)
        return deps.tools
    if source in _FAILING_TOOL_SETS:
        _FAILING_TOOL_SETS.discard(source)
        logger.info("per-turn tool set recovered")
    return tools


def _speaks_reply(session: Session, deps: TurnDeps) -> bool:
    """Whether this turn's reply will be synthesized (the gate before speak_reply)."""
    return bool(session.speak and deps.voice_service is not None
                and deps.voice_service.tts_available)


async def run_turn(session: Session, deps: TurnDeps, text: str, cancel: CancelToken,
                   *, spoken_input: bool, think: bool | None,
                   rethink_of: str | None = None) -> None:
    turn_started_at = time.monotonic()
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
    # RFC-0013 §5 ruling P5: the route is pinned once per turn; every call of the
    # turn gets it, so a default changed mid-turn applies from the next turn.
    category = CATEGORY_OF[classify_task(text)]
    try:
        pinned = deps.model_service.turn_route()
    except Exception:  # noqa: BLE001 - an unreadable saved default is ignored, never an error
        logger.warning("saved default lookup failed; using the router's order", exc_info=True)
        pinned = None
    # No saved default at turn start -> CONFIG_ORDER: the configured order for the
    # whole turn, never re-reading the default (route=None would look it up per call).
    turn_pin = pinned if pinned is not None else CONFIG_ORDER
    # The thinking check names the pinned model (it can take PROBE_TIMEOUT_S).
    effective, unsupported_reason = await resolve_think(session, deps, think, route=turn_pin)
    recorder = ThinkingRecorder(turn_id)
    ctx = session.root.child(turn_id, cancel=cancel)
    session.begin_turn()
    session.enqueue(Frame(channel=CHAT, type="turn.start", payload={
        "turn_id": turn_id, "think": effective, "rethink_of": rethink_of}))

    answered: list[RouteChoice] = []  # the last route that answered is who answered

    def _on_loading(route: RouteChoice) -> None:
        session.enqueue(Frame(channel=CHAT, type="model.loading", payload={
            "turn_id": turn_id, "provider": route.provider, "model": route.model}))

    routing = {"route": turn_pin, "on_route": answered.append, "on_loading": _on_loading}

    def _think_fields() -> dict:
        return {"model": _route_dict(answered[-1] if answered else None), "category": category,
                "think": effective, "thinking_ms": recorder.total_ms,
                "think_unsupported_reason": unsupported_reason, "rethink_of": rethink_of}

    final = ""
    end_extra: dict = {}
    prefix: asyncio.Task | None = None
    pacer: SpeechPacer | None = None
    speaker: StreamingSpeaker | None = None
    try:
        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": "", "cancelled": True, **_think_fields()}))
            return

        await _emit_model_chosen(ctx, deps, turn_id, category, pinned)

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

        tools = _turn_tools(deps)
        if tools:
            messages = build_messages(context, text, modality, prefs)
            metas = [getattr(t, "meta", None) for t in tools]
            servers = {m.name: m.server for m in metas if getattr(m, "server", None)}

            def _frame(event: ToolEvent) -> None:
                server = {"server": servers[event.name]} if event.name in servers else {}
                if isinstance(event, ToolCallStarted):
                    session.enqueue(Frame(channel=TOOLS, type="call", payload={
                        "call_id": event.call_id, "tool": event.name,
                        "arguments": dict(event.arguments), **server}))
                else:  # ToolCallFinished
                    r = event.result
                    payload = {"call_id": event.call_id, "tool": event.name, "ok": r.ok}
                    if r.ok:
                        payload["output"] = _json_safe(r.output)
                    else:
                        payload["error_code"] = r.error_code
                        payload["error_message"] = r.error_message
                    session.enqueue(Frame(channel=TOOLS, type="result", payload={**payload, **server}))

            agent_result = await run_agentic_loop(
                ctx, model_service=deps.model_service, tool_service=deps.tool_service,
                tools=tools, messages=messages, config=deps.tool_loop_config, observer=_frame,
                think=effective, thinking=recorder, **routing)
            final = agent_result.text
            end_extra = {"stop_reason": agent_result.stop_reason, "iterations": agent_result.iterations}
        elif not deps.reasoning_enabled:
            request = GenerationRequest(messages=build_messages(context, text, modality, prefs),
                                        think=effective)
            thinking = TailBuffer()  # bounded, filled chunk by chunk (RFC-0012 §6)
            if speaks:  # speak sentence by sentence as the reply streams
                pacer = SpeechPacer()
                speaker = StreamingSpeaker(session, deps.voice_service, ctx, turn_id,
                                           turn_started_at=turn_started_at, wait_for=prefix)
            started = time.monotonic()
            first_text_at: float | None = None
            async for chunk in deps.model_service.stream(ctx, request, **routing):
                if chunk.thinking:
                    thinking.append(chunk.thinking)
                if ctx.cancelled:
                    break
                if chunk.text:
                    if first_text_at is None:
                        first_text_at = time.monotonic()
                    final += chunk.text
                    session.enqueue(Frame(channel=CHAT, type="token", payload={"text": chunk.text}))
                    if speaker is not None:
                        speaker.say(pacer.feed(chunk.text))
            ended = first_text_at if first_text_at is not None else time.monotonic()
            await recorder.record(ctx, step="direct", index=0, text=thinking,
                                  elapsed_ms=int((ended - started) * 1000))
        else:
            reasoning = deps.reasoning_factory()
            result = await reasoning.run(ctx, ReasoningInput(
                prompt=text, context=context, system=system_texts(modality, prefs),
                think=effective), thinking=recorder, **routing)
            final = result.text
            end_extra = {
                "confidence": result.final_confidence,
                "loops": result.loops_used,
                "halted_early": result.halted_early,
            }

        if ctx.cancelled:
            session.enqueue(Frame(channel=CHAT, type="turn.end",
                                  payload={"text": final, "cancelled": True, **_think_fields()}))
            return

        if deps.memory_service is not None:
            deps.memory_service.store(ctx, text=format_exchange(text, final))

        payload = {"text": final, **end_extra, **_think_fields()}
        session.enqueue(Frame(channel=CHAT, type="turn.end", payload=payload))

        if speaker is not None:
            speaker.say(pacer.finish())
            await speaker.close(pacer)
        if prefix is not None:
            await prefix
        if speaker is None and _speaks_reply(session, deps) and final and not ctx.cancelled:
            await speak_reply(session, deps.voice_service, ctx, final, turn_id)
    except Exception:  # noqa: BLE001 - a failed turn must not kill the session
        logger.exception("turn failed")
        session.enqueue(Frame(channel=CHAT, type="error", payload={"message": "generation failed"}))
        if speaker is not None:  # report the failure, then speak what was complete
            speaker.say(pacer.flush_complete())
            await speaker.close(pacer)
    finally:
        try:
            if prefix is not None:
                if not prefix.done():
                    prefix.cancel()
                await asyncio.gather(prefix, return_exceptions=True)
            if speaker is not None:
                await speaker.abort(pacer)  # no-op once closed; ends a cancelled speech
        finally:  # a second cancel during teardown must not leave the turn "running"
            session.end_turn()
        # RFC-0012 §2: a support change (e.g. Ollama warmed up since connect) is
        # re-announced. Backgrounded: barge-in awaits this task, and a cold probe
        # can take PROBE_TIMEOUT_S. Normally a cache hit, sending nothing.
        if getattr(deps, "thinking_support", None) is not None and session.connected:
            schedule_think_state(session, deps, only_if_changed=True)
