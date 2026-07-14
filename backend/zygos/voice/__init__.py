"""Voice interaction runtime (RFC-0005). Framework-free; the web layer lives in zygos/api/."""
from __future__ import annotations

from zygos.voice.service import VoiceService, build_stt_plugin, build_tts_plugin

__all__ = ["VoiceService", "build_stt_plugin", "build_tts_plugin"]
