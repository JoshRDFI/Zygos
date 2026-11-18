"""Secret store protocol, errors and presence type.

Values are never included in exception messages or reprs.

Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

EXTRA_MISSING = "install the secrets extra: pip install -e '.[secrets]'"


class SecretStoreError(Exception):
    """Base class for secret store failures."""


class SecretStoreUnavailable(SecretStoreError):
    """The store cannot be used right now (missing extra, locked keychain, ...)."""


class SecretStoreCorrupt(SecretStoreError):
    """Stored secret data exists but cannot be read."""


class InvalidHandle(SecretStoreError, ValueError):
    """A secret handle does not match the handle grammar."""


@runtime_checkable
class SecretStore(Protocol):
    name: str

    def get(self, handle: str) -> str | None: ...

    def set(self, handle: str, value: str) -> None: ...

    def delete(self, handle: str) -> None: ...

    def availability(self) -> str | None:
        """None when usable, otherwise a human-readable reason."""
        ...


@dataclass(frozen=True)
class Presence:
    state: Literal["set", "not_set", "unknown"]
    reason: str | None = None
