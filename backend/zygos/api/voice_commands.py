"""Deterministic spoken thinking phrases, matched on the STT final (RFC-0012 §4).

No model is involved: the transcript is matched against a fixed phrase set before a
turn runs. Typed text is never parsed (only ``zygos.api.audio`` calls this).

Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

_STRIP = " \t\r\n.,!?;:\"'…-"
_BOUNDARY = ",.:;!?- \t\r\n"

_THINK_TURN = ("think about this", "think about it", "think it through", "think carefully")
_RETHINK = ("think harder", "think about that", "think it through")
_ON = ("turn thinking on", "thinking on")
_OFF = ("turn thinking off", "thinking off")


@dataclass(frozen=True)
class VoiceCommand:
    command: Literal["think_turn", "rethink", "think_on", "think_off"]
    phrase: str
    rest: str = ""


def parse_voice_command(text: str) -> VoiceCommand | None:
    norm = text.lower().strip(_STRIP)
    if norm in _RETHINK:
        return VoiceCommand("rethink", norm, "")
    if norm in _ON:
        return VoiceCommand("think_on", norm, "")
    if norm in _OFF:
        return VoiceCommand("think_off", norm, "")
    stripped = text.lstrip(_STRIP + " ")
    lowered = stripped.lower()
    for phrase in _THINK_TURN:
        if lowered.startswith(phrase):
            tail = stripped[len(phrase):]
            if not tail or tail[0] not in _BOUNDARY:
                continue
            rest = tail.lstrip(_BOUNDARY).strip()
            if rest:
                return VoiceCommand("think_turn", phrase, rest)
    return None
