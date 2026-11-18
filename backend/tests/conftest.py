"""Suite-wide fixtures.

No test may reach the real OS keychain (on WSL2 a Secret Service call over D-Bus
can hang): ``keyring.get_keyring`` is replaced with a fail-backend for every test.
Tests that need a working keychain inject a fake backend explicitly.
"""

import importlib.util

import pytest


class _NoKeyring:
    """Looks like keyring's fail backend (unusable keychain)."""


_NoKeyring.__module__ = "keyring.backends.fail"


@pytest.fixture(autouse=True)
def _no_real_keychain(monkeypatch):
    if importlib.util.find_spec("keyring") is None:
        return
    import keyring

    monkeypatch.setattr(keyring, "get_keyring", lambda: _NoKeyring())
