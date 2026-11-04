"""User personalization model: how the assistant addresses the user and presents itself.

All fields are optional; blank/whitespace input normalizes to ``None``. Bounds live in
``FIELD_MAX_LENGTHS`` so every producer (CLI, onboarding drafts) clips to the same limits.

Stability: Experimental.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

PERSONALIZATION_FIELDS: tuple[str, ...] = (
    "user_name",
    "address",
    "pronouns",
    "assistant_name",
    "tone",
    "persona",
)

FIELD_MAX_LENGTHS: dict[str, int] = {
    "user_name": 64,
    "address": 64,
    "pronouns": 64,
    "assistant_name": 64,
    "tone": 120,
    "persona": 600,
}


class Personalization(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_name: str | None = None
    address: str | None = None
    pronouns: str | None = None
    assistant_name: str | None = None
    tone: str | None = None
    persona: str | None = None

    @field_validator(*PERSONALIZATION_FIELDS, mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @model_validator(mode="after")
    def _check_lengths(self) -> Personalization:
        for name, limit in FIELD_MAX_LENGTHS.items():
            value = getattr(self, name)
            if value is not None and len(value) > limit:
                raise ValueError(f"{name} exceeds {limit} characters")
        return self

    @property
    def is_empty(self) -> bool:
        return all(getattr(self, name) is None for name in PERSONALIZATION_FIELDS)
