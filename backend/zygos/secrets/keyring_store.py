"""OS keychain secret store (via the ``keyring`` library).

One keychain service per install: ``zygos:<install_id>``; the handle is the
username. ``keyring`` is imported lazily. Availability is probed with a read
only (never a write) in a daemon thread bounded by ``probe_timeout``, because a
locked keychain can block on a prompt.

Stability: Experimental.
"""

from __future__ import annotations

import threading
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
        result: dict[str, str | None] = {}

        def probe() -> None:
            # Backend discovery (keyring config, D-Bus) runs here too, so it is
            # bounded by the probe timeout and its errors become a reason.
            try:
                backend = self._resolve()
                why = self._unusable(backend)
                if why is None:
                    try:
                        backend.get_password(self.service or _PROBE_SERVICE, _PROBE_USER)  # type: ignore[attr-defined]
                    except Exception as exc:
                        why = str(self._map(exc, backend))
                result["why"] = why
            except SecretStoreUnavailable as exc:
                result["why"] = str(exc)

        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        thread.join(self._probe_timeout)
        if thread.is_alive() or "why" not in result:
            return f"keychain didn't answer within {self._probe_timeout:g}s (locked?)"
        return result["why"]

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
        why = self._unusable(backend)
        if why is not None:
            raise SecretStoreUnavailable(why)  # never write to a plain-text "keychain"
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
            try:
                backend = keyring.get_keyring()
            except Exception as exc:
                # Never str(exc); a broken keyring config or D-Bus error is a reason.
                raise SecretStoreUnavailable(f"keychain error ({type(exc).__name__})") from None
            self._backend = backend
        return self._backend

    @staticmethod
    def _unusable(backend: object) -> str | None:
        """Why ``backend`` is not a real OS keychain, or None. No I/O."""
        label = type(backend).__name__
        module = type(backend).__module__
        if module in _DEAD_MODULES:
            return f"no usable OS keychain ({label}, {_DEAD_MODULES[module]} backend)"
        if module == "keyring.backends.chainer":
            members = getattr(backend, "backends", None) or ()
            if not members:
                return f"no usable OS keychain ({label}, no backends)"
            if all(_priority(m) is None or _priority(m) < 1 for m in members):  # type: ignore[operator]
                return f"no usable OS keychain ({label}, only low-priority backends)"
            return None
        priority = _priority(backend)
        if priority is None:
            return f"no usable OS keychain ({label}, unknown priority)"
        if priority < 1:
            # e.g. keyrings.alt PlaintextKeyring (0.5): plain text is not a keychain.
            return f"no usable OS keychain ({label}, priority {priority:g})"
        return None

    @staticmethod
    def _map(exc: BaseException, backend: object) -> SecretStoreUnavailable:
        # Never str(exc): backend errors may echo secret material.
        return SecretStoreUnavailable(
            f"keychain error ({type(exc).__name__} from {type(backend).__name__})"
        )


def _priority(backend: object) -> float | None:
    try:
        value = getattr(backend, "priority", None)
    except Exception:  # keyring's priority raises for a non-viable backend
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
