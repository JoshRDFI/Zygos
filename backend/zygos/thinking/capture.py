"""Thinking capture: a tail-keeping buffer, and a per-turn recorder that emits
``model.thinking`` bus events (RFC-0012 §6). Thinking text goes only to the
event bus (trace), never to chat frames, TTS or memory.
"""

from __future__ import annotations

from typing import Literal

from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import ModelThinking

MAX_THINKING_EVENT_CHARS = 32_000

Step = Literal["direct", "tool_loop", "prelude", "recurrent", "judge", "coda"]


class TailBuffer:
    """Keeps only the last ``cap`` characters appended."""

    def __init__(self, cap: int = MAX_THINKING_EVENT_CHARS) -> None:
        self._cap = cap
        self._text = ""
        self._chars = 0

    def append(self, text: str) -> None:
        self._chars += len(text)
        self._text = (self._text + text)[-self._cap:]

    @property
    def text(self) -> str:
        return self._text

    @property
    def chars(self) -> int:
        return self._chars

    @property
    def truncated(self) -> bool:
        return self._chars > self._cap


class ThinkingRecorder:
    def __init__(self, turn_id: str) -> None:
        self._turn_id = turn_id
        self._total_ms: int | None = None

    async def record(self, ctx: ExecutionContext, *, step: Step, index: int,
                     text: str | None, elapsed_ms: int) -> None:
        if not text:
            return
        buf = TailBuffer()
        buf.append(text)
        self._total_ms = (self._total_ms or 0) + elapsed_ms
        await ctx.emit(
            ModelThinking(turn_id=self._turn_id, step=step, index=index, text=buf.text,
                          truncated=buf.truncated, chars=buf.chars, elapsed_ms=elapsed_ms),
            source="thinking",
        )

    @property
    def total_ms(self) -> int | None:
        return self._total_ms
