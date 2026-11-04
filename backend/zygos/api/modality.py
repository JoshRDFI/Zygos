"""Per-turn interaction-modality context (RFC-0010 §3a).

Tells the model how *this* turn is happening: whether the user's words arrived as a
speech-to-text transcript, and whether the reply will be read aloud. Derived per
turn by the turn loop, never stored. A fixed, runtime-authored template: no user
text and no model call. Typed turns with spoken output off render nothing.

Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass

_SPOKEN_INPUT = (
    "The user is speaking to you. Their words reach you as a speech-to-text "
    "transcript, so treat them as speech and allow for recognition errors (misheard "
    "or missing words): interpret charitably, and ask for clarification only when "
    "the meaning is genuinely unclear."
)

_SPOKEN_OUTPUT = (
    "Your reply will be read aloud by text-to-speech. Write it as natural "
    "conversational speech: no markdown, headings, bullet lists, tables, code "
    "blocks, or raw URLs. Keep it concise, and spell out anything that would read "
    "badly aloud."
)


@dataclass(frozen=True)
class TurnModality:
    spoken_input: bool = False   # text is an STT transcript (turn started from audio)
    spoken_output: bool = False  # reply will be synthesized (speaker on and TTS available)


def render_modality(modality: TurnModality) -> str | None:
    """The modality system message, or None when there is nothing to say."""
    parts = []
    if modality.spoken_input:
        parts.append(_SPOKEN_INPUT)
    if modality.spoken_output:
        parts.append(_SPOKEN_OUTPUT)
    return " ".join(parts) or None
