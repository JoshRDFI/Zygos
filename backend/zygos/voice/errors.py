from __future__ import annotations

from zygos.errors import ZygosError


class VoiceError(ZygosError):
    """Base for voice-subsystem failures."""
    code = "voice_error"


class SidecarSpawnError(VoiceError):
    code = "voice_sidecar_spawn_failed"


class SidecarCrashed(VoiceError):
    code = "voice_sidecar_crashed"


class IpcProtocolError(VoiceError):
    code = "voice_ipc_protocol_error"


class TranscriptionFailed(VoiceError):
    code = "voice_transcription_failed"
