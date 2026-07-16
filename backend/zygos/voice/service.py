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
    from zygos.config.schema import SttConfig, TtsConfig

_DEFAULT_FW_DOWNLOAD_ROOT = ".zygos/models/faster-whisper"
_DEFAULT_KOKORO_DOWNLOAD_ROOT = ".zygos/models/kokoro"

_STT_ENGINES: dict[str, SttEngineSpec] = {
    "fake": SttEngineSpec(name="fake", argv=(sys.executable, "-m", "zygos.voice.sidecar.fake_stt")),
    # "faster_whisper" is built per-config in build_stt_plugin (needs env params).
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
    # "kokoro" is built per-config in build_tts_plugin (needs env params).
}


def build_tts_plugin(tts: TtsConfig) -> TtsPlugin:
    if tts.engine == "fake":
        return TtsPlugin(_TTS_ENGINES["fake"], readiness_timeout_s=tts.readiness_timeout_s)
    if tts.engine == "kokoro":
        download_root = tts.download_root or str(Path(_DEFAULT_KOKORO_DOWNLOAD_ROOT))
        spec = TtsEngineSpec(
            name="kokoro",
            argv=(sys.executable, "-m", "zygos.voice.sidecar.kokoro"),
            device=tts.device,
            concurrent_safe=False,
            env={
                "ZYGOS_TTS_VOICE": tts.voice,
                "ZYGOS_TTS_LANG": tts.lang,
                "ZYGOS_TTS_DOWNLOAD_ROOT": download_root,
            },
        )
        return TtsPlugin(spec, readiness_timeout_s=tts.readiness_timeout_s)
    raise VoiceError(f"unknown TTS engine {tts.engine!r}")


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

    async def ensure_stt_ready(self, ctx: ExecutionContext) -> None:
        if self._stt is not None:
            await self._stt.ensure_alive()

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
