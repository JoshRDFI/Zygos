"""Suite-wide fixtures.

No test may reach the real OS keychain (on WSL2 a Secret Service call over D-Bus
can hang): ``keyring.get_keyring`` is replaced with a fail-backend for every test.
Tests that need a working keychain inject a fake backend explicitly.
"""

import importlib.util
from pathlib import Path
from urllib.parse import urljoin

import pytest
from starlette.testclient import TestClient

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


# --- Session guard: the suite must never write into the real backend/.zygos ---

_REAL_DATA_DIR = Path(__file__).resolve().parents[1] / ".zygos"
_before_files: set[str] = set()
_live_ran = False


def _snapshot_files(folder: Path) -> set[str]:
    if not folder.is_dir():
        return set()
    return {str(p) for p in folder.rglob("*") if p.is_file()}


def _new_files(before: set[str], after: set[str]) -> set[str]:
    return after - before


def pytest_sessionstart(session):
    global _before_files, _live_ran
    _live_ran = False
    _before_files = _snapshot_files(_REAL_DATA_DIR)


def pytest_runtest_setup(item):
    global _live_ran
    if {m.name for m in item.iter_markers()} & _REAL_ROOT_MARKERS:
        _live_ran = True


def pytest_sessionfinish(session, exitstatus):
    if _live_ran:
        return
    new = _new_files(_before_files, _snapshot_files(_REAL_DATA_DIR))
    if new:
        print(f"\nTests wrote into the real {_REAL_DATA_DIR}:")
        for name in sorted(new):
            print(f"  {name}")
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def _client_talks_to_localhost(monkeypatch):
    """Starlette's TestClient sends ``Host: testserver``, which the Host guard
    rightly refuses. Tests talk to the app the way a browser on this machine does,
    so the client defaults to ``http://localhost``. Tests of the guard itself pass an
    explicit ``Host`` header."""
    original = TestClient.__init__

    def init(self, app, base_url="http://localhost", *args, **kwargs):
        original(self, app, base_url, *args, **kwargs)

    monkeypatch.setattr(TestClient, "__init__", init)

    # websocket_connect resolves relative URLs against a hard-coded ws://testserver.
    original_ws = TestClient.websocket_connect

    def websocket_connect(self, url, *args, **kwargs):
        return original_ws(self, urljoin("ws://localhost", url), *args, **kwargs)

    monkeypatch.setattr(TestClient, "websocket_connect", websocket_connect)
