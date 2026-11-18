"""Choosing the secret store for this install, and the handle callers use.

Resolution runs on every call, because another process may record the choice at
any time. Order (RFC-0015 phase 0, "How the store is chosen"):

1. ``secrets.backend: encrypted_file`` in config → the file store, always; the
   record is neither read nor written (the file needs no install id).
2. Read the recorded choice. An unreadable record makes secrets unavailable — it
   is never treated as "no record".
3. ``secrets.backend: keyring`` in config → the keychain, with the install id from
   the record (recorded at the first ``set`` if there is none).
4. A record → its store, even if unavailable right now. **No fallback.**
5. No record but ``secrets.enc`` exists → the file store (that file is evidence of
   saved secrets); recorded at the first ``set``.
6. Otherwise provisional: keychain if usable, else encrypted file, else none.

Reads (``status``/``get``/``presence``) never write. The first ``set`` without a
record records the choice *before* writing the secret; if recording fails nothing
is written. A process that loses a first-save race follows the winner's record.

Building the handle does no I/O and imports neither ``keyring`` nor
``cryptography``. The keychain availability probe is cached for the life of the
handle (a locked keychain can take seconds to answer); file availability is
checked on each call.

Stability: Experimental.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from zygos.config.schema import ZygosConfig
from zygos.secrets.choice import ChoiceRecord, SqliteChoiceStore
from zygos.secrets.file_store import EncryptedFileStore
from zygos.secrets.handles import validate_handle
from zygos.secrets.keyring_store import KeyringStore
from zygos.secrets.types import (
    EXTRA_MISSING,
    InvalidHandle,
    Presence,
    SecretStore,
    SecretStoreError,
    SecretStoreUnavailable,
)

KEYRING = "keyring"
ENCRYPTED_FILE = "encrypted_file"
_KNOWN = (KEYRING, ENCRYPTED_FILE)

REASON_CONFIG = "set in config"
REASON_PROVISIONAL = "provisional — nothing saved yet"
REASON_ADOPTED = "found an existing secrets file"
# Not one of the four planned reasons: an unreadable record has no date and
# must not read as provisional.
REASON_UNREADABLE = "recorded choice unreadable"

_UNSET = object()


def _chosen_reason(record: ChoiceRecord) -> str:
    try:
        day = datetime.fromisoformat(record.chosen_at).date().isoformat()
    except ValueError:
        day = record.chosen_at[:10]
    return f"chosen {day} at first save"


def _pinned_unavailable(name: str, why: str) -> str:
    return f"secrets are in {name}, which isn't available right now: {why}"


@dataclass(frozen=True)
class SecretsStatus:
    backend: str | None
    reason: str
    available: bool
    why_unavailable: str | None
    location: str | None


@dataclass(frozen=True)
class _Resolution:
    backend: str | None
    reason: str
    store: SecretStore | None
    why_unavailable: str | None
    location: str | None
    # Backend to record (before writing) at the first set; None = nothing to record.
    to_record: str | None = None

    @property
    def available(self) -> bool:
        return self.why_unavailable is None

    def require(self) -> SecretStore:
        if self.why_unavailable is not None or self.store is None:
            raise SecretStoreUnavailable(self.why_unavailable or "no secret store")
        return self.store


class SecretsHandle:
    """The install's secret store, chosen per call. Never exposes values in reprs."""

    def __init__(
        self,
        *,
        configured: str,
        directory: Path,
        choice: SqliteChoiceStore,
        keyring_backend: object | None,
        now: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self._configured = configured
        self._file = EncryptedFileStore(directory)
        self._choice = choice
        self._keyring_backend = keyring_backend
        self._now = now
        self._new_id = new_id
        self._keyrings: dict[str | None, KeyringStore] = {}
        self._keyring_why: object = _UNSET

    def __repr__(self) -> str:
        return f"SecretsHandle({self._configured}, {self._file.directory})"

    # -- public API ---------------------------------------------------------

    def status(self) -> SecretsStatus:
        r = self._resolve()
        return SecretsStatus(
            backend=r.backend,
            reason=r.reason,
            available=r.available,
            why_unavailable=r.why_unavailable,
            location=r.location,
        )

    def get(self, handle: str) -> str | None:
        validate_handle(handle)
        return self._resolve().require().get(handle)

    def set(self, handle: str, value: str) -> None:
        validate_handle(handle)
        r = self._resolve()
        store = r.require()
        if r.to_record is not None:
            record = self._choice.record_if_absent(
                ChoiceRecord(
                    backend=r.to_record,
                    chosen_at=self._now().isoformat(),
                    install_id=self._new_id(),
                )
            )
            name = r.backend if self._configured != "auto" else record.backend
            store = self._pinned_store(name, record.install_id)
        store.set(handle, value)

    def delete(self, handle: str) -> None:
        validate_handle(handle)
        r = self._resolve()
        store = r.require()
        if isinstance(store, KeyringStore) and store.service is None:
            return  # no install id yet: nothing has ever been saved there
        store.delete(handle)

    def presence(self, handle: str) -> Presence:
        validate_handle(handle)
        try:
            value = self.get(handle)
        except InvalidHandle:
            raise
        except SecretStoreError as exc:
            return Presence("unknown", str(exc))
        return Presence("set" if value is not None else "not_set")

    def file_store(self) -> EncryptedFileStore:
        return self._file

    # -- resolution ---------------------------------------------------------

    def _resolve(self) -> _Resolution:
        if self._configured == ENCRYPTED_FILE:
            return self._pinned(ENCRYPTED_FILE, REASON_CONFIG, None)
        try:
            record = self._choice.read()
        except SecretStoreUnavailable as exc:
            if self._configured == KEYRING:
                why = _pinned_unavailable(
                    KEYRING, f"this install's id can't be read, so its entries can't be found ({exc})"
                )
                return _Resolution(KEYRING, REASON_CONFIG, None, why, None)
            return _Resolution(None, REASON_UNREADABLE, None, str(exc), None)

        if self._configured == KEYRING:
            if record is None:
                return self._pinned(KEYRING, REASON_CONFIG, None, to_record=KEYRING)
            return self._pinned(KEYRING, REASON_CONFIG, record.install_id)
        if record is not None:
            return self._pinned(record.backend, _chosen_reason(record), record.install_id)
        if self._file.enc_path.exists():
            return self._pinned(ENCRYPTED_FILE, REASON_ADOPTED, None, to_record=ENCRYPTED_FILE)
        return self._provisional()

    def _pinned(
        self, name: str, reason: str, install_id: str | None, *, to_record: str | None = None
    ) -> _Resolution:
        if name not in _KNOWN:
            why = f"the record names a store Zygos doesn't know: {name}"
            return _Resolution(name, reason, None, why, None)
        store = self._store(name, install_id)
        why = self._availability(name, store)
        return _Resolution(
            backend=name,
            reason=reason,
            store=store,
            why_unavailable=None if why is None else _pinned_unavailable(name, why),
            location=self._location(store),
            to_record=to_record,
        )

    def _provisional(self) -> _Resolution:
        keyring = self._store(KEYRING, None)
        keyring_why = self._availability(KEYRING, keyring)
        if keyring_why is None:
            return self._provisional_on(KEYRING, keyring)
        file_why = self._file.availability()
        if file_why is None:
            return self._provisional_on(ENCRYPTED_FILE, self._file)
        if keyring_why == EXTRA_MISSING and file_why == EXTRA_MISSING:
            why = EXTRA_MISSING
        else:
            why = f"keyring: {keyring_why}; encrypted_file: {file_why}"
        return _Resolution(
            backend=None,
            reason=REASON_PROVISIONAL,
            store=None,
            why_unavailable=why,
            location=None,
        )

    def _provisional_on(self, name: str, store: SecretStore) -> _Resolution:
        return _Resolution(
            backend=name,
            reason=REASON_PROVISIONAL,
            store=store,
            why_unavailable=None,
            location=self._location(store),
            to_record=name,
        )

    def _pinned_store(self, name: str, install_id: str) -> SecretStore:
        """The store a just-read record pins; raises if it can't be used now."""
        if name not in _KNOWN:
            raise SecretStoreUnavailable(f"the record names a store Zygos doesn't know: {name}")
        store = self._store(name, install_id)
        why = self._availability(name, store)
        if why is not None:
            raise SecretStoreUnavailable(_pinned_unavailable(name, why))
        return store

    def _store(self, name: str, install_id: str | None) -> SecretStore:
        if name == ENCRYPTED_FILE:
            return self._file
        store = self._keyrings.get(install_id)
        if store is None:
            store = KeyringStore(install_id, backend=self._keyring_backend)
            self._keyrings[install_id] = store
        return store

    def _availability(self, name: str, store: SecretStore) -> str | None:
        if name == ENCRYPTED_FILE:
            return store.availability()
        if self._keyring_why is _UNSET:
            self._keyring_why = store.availability()
        return self._keyring_why  # type: ignore[return-value]

    @staticmethod
    def _location(store: SecretStore) -> str | None:
        if isinstance(store, EncryptedFileStore):
            return str(store.enc_path)
        if isinstance(store, KeyringStore):
            return store.service
        return None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_hex() -> str:
    return uuid.uuid4().hex


def build_secret_store(
    config: ZygosConfig,
    *,
    keyring_backend: object | None = None,
    now: Callable[[], datetime] = _utc_now,
    new_id: Callable[[], str] = _uuid_hex,
) -> SecretsHandle:
    """Build the install's secrets handle. No I/O and no optional imports here."""
    db_path = Path(config.personalization.db_path)
    return SecretsHandle(
        configured=config.secrets.backend,
        directory=db_path.parent,
        choice=SqliteChoiceStore(db_path),
        keyring_backend=keyring_backend,
        now=now,
        new_id=new_id,
    )
