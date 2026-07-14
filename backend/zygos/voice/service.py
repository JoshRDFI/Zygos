from __future__ import annotations

import sys
from dataclasses import dataclass

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth
from zygos.voice.errors import VoiceError
from zygos.voice.plugin import SttPlugin, Transcription
from zygos.voice.types import SttEngineSpec

_STT_ENGINES: dict[str, SttEngineSpec] = {
    "fake": SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt")),
    # "whisper_cpp": added in the next increment (real engine).
}


def build_stt_plugin(engine: str) -> SttPlugin:
    spec = _STT_ENGINES.get(engine)
    if spec is None:
        raise VoiceError(f"unknown STT engine {engine!r}; available: {sorted(_STT_ENGINES)}")
    return SttPlugin(spec)


@dataclass(frozen=True)
class VoiceState:
    stt: SttHealth | None


class VoiceService:
    """Runtime-side facade over the active voice plugins (RFC-0001 §2)."""

    def __init__(self, *, stt: SttPlugin | None) -> None:
        self._stt = stt

    @property
    def stt_available(self) -> bool:
        return self._stt is not None

    async def start(self, ctx: ExecutionContext) -> None:
        if self._stt is not None:
            await self._stt.start()

    def begin_transcription(self, ctx: ExecutionContext) -> Transcription:
        if self._stt is None:
            raise VoiceError("no speech_to_text engine registered")
        return self._stt.begin(ctx)

    def synthesize_stream(self, *args, **kwargs):  # Cycle 2 seam
        raise NotImplementedError("text_to_speech lands in Voice Cycle 2")

    def snapshot(self) -> VoiceState:
        return VoiceState(stt=self._stt.health() if self._stt is not None else None)

    async def aclose(self) -> None:
        if self._stt is not None:
            await self._stt.aclose()
