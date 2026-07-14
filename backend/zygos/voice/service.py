from __future__ import annotations

import sys
from dataclasses import dataclass

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth, TtsHealth
from zygos.voice.errors import VoiceError
from zygos.voice.plugin import SttPlugin, Transcription, TtsPlugin
from zygos.voice.types import AudioFormat, SttEngineSpec, TtsEngineSpec

_STT_ENGINES: dict[str, SttEngineSpec] = {
    "fake": SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt")),
    # "whisper_cpp": added in the next increment (real engine).
}


def build_stt_plugin(engine: str) -> SttPlugin:
    spec = _STT_ENGINES.get(engine)
    if spec is None:
        raise VoiceError(f"unknown STT engine {engine!r}; available: {sorted(_STT_ENGINES)}")
    return SttPlugin(spec)


_TTS_ENGINES: dict[str, TtsEngineSpec] = {
    "fake": TtsEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_tts")),
    # "kokoro" / "piper": added in the next increment (real engines).
}


def build_tts_plugin(engine: str) -> TtsPlugin:
    spec = _TTS_ENGINES.get(engine)
    if spec is None:
        raise VoiceError(f"unknown TTS engine {engine!r}; available: {sorted(_TTS_ENGINES)}")
    return TtsPlugin(spec)


@dataclass(frozen=True)
class VoiceState:
    stt: SttHealth | None
    tts: TtsHealth | None = None


class VoiceService:
    """Runtime-side facade over the active voice plugins (RFC-0001 §2)."""

    def __init__(self, *, stt: SttPlugin | None, tts: TtsPlugin | None = None) -> None:
        self._stt = stt
        self._tts = tts

    @property
    def stt_available(self) -> bool:
        return self._stt is not None

    @property
    def tts_available(self) -> bool:
        return self._tts is not None

    @property
    def tts_format(self) -> AudioFormat | None:
        return self._tts.output_format if self._tts is not None else None

    async def start(self, ctx: ExecutionContext) -> None:
        if self._stt is not None:
            await self._stt.start()
        if self._tts is not None:
            await self._tts.start()

    def begin_transcription(self, ctx: ExecutionContext) -> Transcription:
        if self._stt is None:
            raise VoiceError("no speech_to_text engine registered")
        return self._stt.begin(ctx)

    def synthesize_stream(self, ctx: ExecutionContext, text: str):
        if self._tts is None:
            raise VoiceError("no text_to_speech engine registered")
        return self._tts.synthesize(ctx, text)

    def snapshot(self) -> VoiceState:
        return VoiceState(
            stt=self._stt.health() if self._stt is not None else None,
            tts=self._tts.health() if self._tts is not None else None,
        )

    async def aclose(self) -> None:
        if self._stt is not None:
            await self._stt.aclose()
        if self._tts is not None:
            await self._tts.aclose()
