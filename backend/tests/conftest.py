"""Suite-wide fixtures.

No test may reach the real OS keychain (on WSL2 a Secret Service call over D-Bus
can hang): ``keyring.get_keyring`` is replaced with a fail-backend for every test.
Tests that need a working keychain inject a fake backend explicitly.
"""

import importlib.util
from pathlib import Path

import pytest

from zygos.home import reset_zygos_home_cache


class _NoKeyring:
    """Looks like keyring's fail backend (unusable keychain)."""


_NoKeyring.__module__ = "keyring.backends.fail"


@pytest.fixture(autouse=True)
def _no_real_keychain(monkeypatch):
    if importlib.util.find_spec("keyring") is None:
        return
    import keyring
    import keyring.core

    fail = _NoKeyring()
    # Patch both the public entry point and the one keyring's own helpers call,
    # and the module-level current backend, so no path reaches the OS keychain.
    monkeypatch.setattr(keyring, "get_keyring", lambda: fail)
    monkeypatch.setattr(keyring.core, "get_keyring", lambda: fail)
    monkeypatch.setattr(keyring.core, "_keyring_backend", fail, raising=False)


_REAL_ROOT_MARKERS = {"live_voice", "live_gpu"}


def _suite_home_env(markers: set[str], tmp: Path | None = None) -> Path | None:
    """ZYGOS_HOME for a test: a temp root, or None (real root) for live tests."""
    if markers & _REAL_ROOT_MARKERS:
        return None
    assert tmp is not None
    return tmp / "zygos-home"


@pytest.fixture(autouse=True)
def _isolated_zygos_home(request, monkeypatch, tmp_path):
    markers = {m.name for m in request.node.iter_markers()}
    path = _suite_home_env(markers, tmp_path)
    if path is not None:
        monkeypatch.setenv("ZYGOS_HOME", str(path))
    else:
        monkeypatch.delenv("ZYGOS_HOME", raising=False)
    reset_zygos_home_cache()
    yield
    reset_zygos_home_cache()
