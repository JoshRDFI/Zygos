"""WebSocket wire envelope and codec (RFC-0007 §1–§2).

A self-describing `{channel, type, payload}` JSON frame. `decode` is tolerant:
malformed input returns None so the reader loop never crashes on bad client data.

Stability: Experimental.
"""

from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict

CHAT = "chat"
TOOLS = "tools"
TRACE = "trace"
CONTROL = "control"
AUDIO_IN = "audio.in"
AUDIO_OUT = "audio.out"

AUDIO_TAG_IN = 0x00  # 1-byte channel tag prefixing binary audio.in frames


class Frame(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    channel: str
    type: str
    payload: dict = {}


def encode(frame: Frame) -> str:
    return frame.model_dump_json()


def decode(raw: str) -> Frame | None:
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return Frame.model_validate(data)
    except Exception:  # noqa: BLE001 - any validation failure = ignore the frame
        return None
