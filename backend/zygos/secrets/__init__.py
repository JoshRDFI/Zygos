"""Per-install secret store: protocol, errors and handle grammar.

Optional libraries (keyring, cryptography) are imported lazily inside backends only.

Stability: Experimental.
"""

from __future__ import annotations

from zygos.secrets.handles import validate_handle
from zygos.secrets.types import (
    EXTRA_MISSING,
    InvalidHandle,
    Presence,
    SecretStore,
    SecretStoreCorrupt,
    SecretStoreError,
    SecretStoreUnavailable,
)

__all__ = [
    "EXTRA_MISSING",
    "InvalidHandle",
    "Presence",
    "SecretStore",
    "SecretStoreCorrupt",
    "SecretStoreError",
    "SecretStoreUnavailable",
    "validate_handle",
]
