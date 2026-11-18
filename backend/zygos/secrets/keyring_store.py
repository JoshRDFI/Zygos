"""OS keychain secret store (via the ``keyring`` library).

One keychain service per install: ``zygos:<install_id>``; the handle is the
username. ``keyring`` is imported lazily. Availability is probed with a read
only (never a write) in a daemon thread bounded by ``probe_timeout``, because a
locked keychain can block on a prompt.

Stability: Experimental.
"""

from __future__ import annotations

import threading
from typing import Any

from zygos.secrets.handles import validate_handle
from zygos.secrets.types import EXTRA_MISSING, SecretStoreUnavailable

_PROBE_USER = "zygos-availability-probe"
_PROBE_SERVICE = "zygos:probe"
_DEAD_MODULES = {"keyring.backends.fail": "fail", "keyring.backends.null": "null"}


class KeyringStore:
    name = "keyring"

    def __init__(
        self,
        install_id: str | None,
        *,
        backend: object | None = None,
        probe_timeout: float = 3.0,
    ) -> None:
        self.service: str | None = f"zygos:{install_id}" if install_id else None
        self._backend = backend
        self._probe_timeout = probe_timeout

    def __repr__(self) -> str:
        return f"KeyringStore({self.service})"

    # -- public API ---------------------------------------------------------

    def availability(self) -> str | None:
        try:
            backend = self._resolve()
        except SecretStoreUnavailable as exc:
            return str(exc)
        label = type(backend).__name__
        module = type(backend).__module__
        if module in _DEAD_MODULES:
            return f"no usable OS keychain ({label}, {_DEAD_MODULES[module]} backend)"
        if module == "keyring.backends.chainer" and not getattr(backend, "backends", None):
            return f"no usable OS keychain ({label}, no backends)"
        result: dict[str, Any] = {}

        def probe() -> None:
            try:
                backend.get_password(self.service or _PROBE_SERVICE, _PROBE_USER)  # type: ignore[attr-defined]
            except Exception as exc:
                result["error"] = self._map(exc, backend)

        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        thread.join(self._probe_timeout)
        if thread.is_alive():
            return f"keychain didn't answer within {self._probe_timeout:g}s (locked?)"
        err = result.get("error")
        return str(err) if err is not None else None

    def get(self, handle: str) -> str | None:
        validate_handle(handle)
        if self.service is None:
            return None
        backend = self._resolve()
        try:
            return backend.get_password(self.service, handle)  # type: ignore[attr-defined,no-any-return]
        except Exception as exc:
            raise self._map(exc, backend) from None

    def set(self, handle: str, value: str) -> None:
        validate_handle(handle)
        service = self._require_service()
        backend = self._resolve()
        try:
            backend.set_password(service, handle, value)  # type: ignore[attr-defined]
        except Exception as exc:
            raise self._map(exc, backend) from None

    def delete(self, handle: str) -> None:
        validate_handle(handle)
        service = self._require_service()
        backend = self._resolve()
        try:
            from keyring.errors import PasswordDeleteError
        except ImportError as exc:
            raise SecretStoreUnavailable(EXTRA_MISSING) from exc
        try:
            backend.delete_password(service, handle)  # type: ignore[attr-defined]
        except PasswordDeleteError:
            return
        except Exception as exc:
            raise self._map(exc, backend) from None

    # -- internals ----------------------------------------------------------

    def _require_service(self) -> str:
        if self.service is None:
            raise SecretStoreUnavailable("no install id")
        return self.service

    def _resolve(self) -> object:
        if self._backend is None:
            try:
                import keyring
            except ImportError as exc:
                raise SecretStoreUnavailable(EXTRA_MISSING) from exc
            self._backend = keyring.get_keyring()
        return self._backend

    @staticmethod
    def _map(exc: BaseException, backend: object) -> SecretStoreUnavailable:
        # Never str(exc): backend errors may echo secret material.
        return SecretStoreUnavailable(
            f"keychain error ({type(exc).__name__} from {type(backend).__name__})"
        )
