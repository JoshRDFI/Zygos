"""Render the user's personalization as a system message (RFC-0010 §3).

Stability: Experimental.
"""

from __future__ import annotations

from zygos.personalization.types import Personalization


def render_identity(prefs: Personalization) -> str | None:
    """The identity system text, or None when nothing is set."""
    if prefs.is_empty:
        return None
    lines: list[str] = []
    if prefs.assistant_name:
        lines.append(f"You are {prefs.assistant_name}, the user's personal assistant.")
    if prefs.user_name:
        lines.append(f"The user's name is {prefs.user_name}.")
    if prefs.address:
        lines.append(f"Address the user as {prefs.address}.")
    if prefs.pronouns:
        lines.append(f"The user's pronouns are {prefs.pronouns}.")
    if prefs.tone:
        tone = prefs.tone if prefs.tone.endswith(".") else f"{prefs.tone}."
        lines.append(f"Tone: {tone}")
    if prefs.persona:
        lines.append(f"Persona, written and approved by the user:\n{prefs.persona}")
    return "\n".join(lines) if lines else None
