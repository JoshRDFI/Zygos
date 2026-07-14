from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from zygos.runtime.context import ExecutionContext
from zygos.voice.types import TranscriptEvent


class SttHealth(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    engine: str
    device: str
    alive: bool
    last_error: str | None = None


@runtime_checkable
class Transcription(Protocol):
    """A single in-flight utterance."""
    async def push(self, pcm: bytes) -> None: ...
    async def endpoint(self) -> None: ...
    def events(self) -> AsyncIterator[TranscriptEvent]: ...
    async def cancel(self) -> None: ...
    async def aclose(self) -> None: ...


@runtime_checkable
class SpeechToText(Protocol):
    """The SPEECH_TO_TEXT capability contract. A concrete engine satisfies this."""
    name: str

    def begin(self, ctx: ExecutionContext) -> Transcription: ...

    def health(self) -> SttHealth: ...
