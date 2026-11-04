"""User personalization: preferred name/address, assistant identity, persona.

Stability: Experimental.
"""

from zygos.personalization.store import PreferencesStore, SqlitePreferencesStore
from zygos.personalization.types import (
    FIELD_MAX_LENGTHS,
    PERSONALIZATION_FIELDS,
    Personalization,
)

__all__ = [
    "FIELD_MAX_LENGTHS",
    "PERSONALIZATION_FIELDS",
    "Personalization",
    "PreferencesStore",
    "SqlitePreferencesStore",
]
