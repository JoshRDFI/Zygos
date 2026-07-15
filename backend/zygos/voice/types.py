from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

SAMPLE_RATE_HZ = 16000
CHANNELS = 1
SAMPLE_FORMAT = "s16le"


class AudioFormat(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    sample_rate: int = SAMPLE_RATE_HZ
    channels: int = CHANNELS
    sample_format: str = SAMPLE_FORMAT


class TranscriptEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["partial", "final"]
    text: str


# --- IPC control messages (JSON bodies), runtime <-> sidecar ---
# runtime -> sidecar
class StartMsg(BaseModel):
    type: Literal["start"] = "start"
    sample_rate: int = SAMPLE_RATE_HZ


class EndMsg(BaseModel):
    type: Literal["end"] = "end"


class CancelMsg(BaseModel):
    type: Literal["cancel"] = "cancel"


class HealthMsg(BaseModel):
    type: Literal["health"] = "health"


# sidecar -> runtime
class PartialMsg(BaseModel):
    type: Literal["partial"] = "partial"
    text: str


class FinalMsg(BaseModel):
    type: Literal["final"] = "final"
    text: str


class HealthOkMsg(BaseModel):
    type: Literal["health_ok"] = "health_ok"


class ErrorMsg(BaseModel):
    type: Literal["error"] = "error"
    message: str


class SttEngineSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    argv: tuple[str, ...]
    device: str = "cpu"
    concurrent_safe: bool = False  # shared local sidecar -> False; API-backed engine -> True


# runtime -> TTS sidecar
class SynthesizeMsg(BaseModel):
    type: Literal["synthesize"] = "synthesize"
    text: str
    sample_rate: int = SAMPLE_RATE_HZ


# TTS sidecar -> runtime (audio arrives as KIND_PCM frames, terminated by this)
class TtsEndMsg(BaseModel):
    type: Literal["end"] = "end"


class TtsEngineSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    argv: tuple[str, ...]
    device: str = "cpu"
    output_sample_rate: int = 24000
    concurrent_safe: bool = False  # shared local sidecar -> False; API-backed engine -> True
