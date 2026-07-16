from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from zygos.runtime.context import ExecutionContext
from zygos.voice.contract import SttHealth, TtsHealth
from zygos.voice.errors import VoiceError
from zygos.voice.plugin import SttPlugin, Transcription, TtsPlugin
from zygos.voice.types import AudioFormat, SttEngineSpec, TtsEngineSpec

if TYPE_CHECKING:
    # Deferred: zygos.config.schema -> zygos.runtime.capabilities -> zygos.voice.contract
    # would otherwise re-enter this package's __init__ mid-import (circular).
    from zygos.config.schema import SttConfig

_DEFAULT_FW_DOWNLOAD_ROOT = ".zygos/models/faster-whisper"

_STT_ENGINES: dict[str, SttEngineSpec] = {
    "fake": SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt")),
    # "whisper_cpp": added in the next increment (real engine).
}


def build_stt_plugin(stt: SttConfig) -> SttPlugin:
    if stt.engine == "fake":
        return SttPlugin(_STT_ENGINES["fake"], readiness_timeout_s=stt.readiness_timeout_s)
    if stt.engine == "faster_whisper":
        download_root = stt.download_root or str(Path(_DEFAULT_FW_DOWNLOAD_ROOT))
        spec = SttEngineSpec(
            name="faster_whisper",
            argv=(sys.executable, "-m", "zygos.voice.sidecar.faster_whisper"),
            device=stt.device,
            concurrent_safe=False,
            env={
                "ZYGOS_STT_MODEL": stt.model,
                "ZYGOS_STT_COMPUTE_TYPE": stt.compute_type,
                "ZYGOS_STT_DEVICE": stt.device,
                "ZYGOS_STT_DOWNLOAD_ROOT": download_root,
            },
        )
        return SttPlugin(spec, readiness_timeout_s=stt.readiness_timeout_s)
    raise VoiceError(f"unknown STT engine {stt.engine!r}")


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

    @property
    def concurrent_sessions_ok(self) -> bool:
        """True iff every active engine can serve concurrent sessions. Shared
        local sidecars are not; a future API-backed engine is. Vacuously True
        with no engines (nothing shared to protect)."""
        return all(p.concurrent_safe for p in (self._stt, self._tts) if p is not None)

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
