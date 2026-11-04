"""Source-labelled model profiles (RFC-0013 §2).

Every fact about a model is stored with where it came from; ``resolve`` picks
the winner by fixed precedence. ``user`` values live in their own section and
are never written by Zygos.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Source = Literal["user", "eval", "measured", "modelfile", "ollama", "name"]
PRECEDENCE: tuple[Source, ...] = ("user", "eval", "measured", "modelfile", "ollama", "name")


class Sourced(BaseModel):
    value: Any
    source: Source
    at: datetime | None = None  # None only for hand-edited user values


class ModelProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    provider: str
    model: str  # first name seen
    names: list[str] = Field(default_factory=list)
    digest: str | None = None
    values: dict[str, list[Sourced]] = Field(default_factory=dict)
    # Overrides by dotted key, plus free `tags: list[str]` and `notes: str`.
    user: dict[str, Any] = Field(default_factory=dict)


def record(profile: ModelProfile, key: str, value: Any, source: Source, at: datetime) -> ModelProfile:
    """Return a copy with exactly one entry for ``source`` under ``key``."""
    if source == "user":
        raise ValueError("Zygos never records user-sourced values; the user edits that section")
    kept = [s for s in profile.values.get(key, []) if s.source != source]
    kept.append(Sourced(value=value, source=source, at=at))
    return profile.model_copy(update={"values": {**profile.values, key: kept}})


def resolve(profile: ModelProfile, key: str) -> Sourced | None:
    if key in profile.user:
        return Sourced(value=profile.user[key], source="user", at=None)
    entries = profile.values.get(key, [])
    if not entries:
        return None
    return min(entries, key=lambda s: PRECEDENCE.index(s.source))


def safe_filename(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", model)
