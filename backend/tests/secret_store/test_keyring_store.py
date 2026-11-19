import sys

import pytest

from secret_store.contract import SecretStoreContract
from secret_store.fakes import FakeKeyring, RaisingKeyring, SlowKeyring
from zygos.secrets import EXTRA_MISSING, SecretStoreUnavailable
from zygos.secrets.keyring_store import KeyringStore

H = "provider:anthropic"


@pytest.fixture
def store():
    return KeyringStore("test-install", backend=FakeKeyring())


class TestKeyringContract(SecretStoreContract):
    pass


def test_two_installs_do_not_share():
    fake = FakeKeyring()
    a = KeyringStore("a", backend=fake)
    b = KeyringStore("b", backend=fake)
    a.set(H, "v")
    assert b.get(H) is None
    assert a.get(H) == "v"


def test_service_name():
    assert KeyringStore("abc", backend=FakeKeyring()).service == "zygos:abc"


def _backend_in(module):
    return type("Keyring", (), {"__module__": module})()


def test_fail_backend_is_unavailable():
    reason = KeyringStore("x", backend=_backend_in("keyring.backends.fail")).availability()
    assert isinstance(reason, str) and "Keyring" in reason


def test_null_backend_and_empty_chainer_unavailable():
    assert isinstance(KeyringStore("x", backend=_backend_in("keyring.backends.null")).availability(), str)
    chainer = _backend_in("keyring.backends.chainer")
    chainer.backends = []
    assert isinstance(KeyringStore("x", backend=chainer).availability(), str)


def test_probe_timeout_is_unavailable():
    s = KeyringStore("x", backend=SlowKeyring(), probe_timeout=0.1)
    assert "didn't answer" in s.availability()


def test_raising_backend_maps_to_unavailable():
    s = KeyringStore("x", backend=RaisingKeyring())
    with pytest.raises(SecretStoreUnavailable) as ei:
        s.get(H)
    assert "RuntimeError" in str(ei.value)
    assert "SENTINEL-77" not in str(ei.value)
    assert "SENTINEL-77" not in repr(ei.value.__cause__)
    assert isinstance(s.availability(), str)
    assert "SENTINEL-77" not in s.availability()


def test_probe_never_writes():
    fake = FakeKeyring()
    assert KeyringStore("x", backend=fake).availability() is None
    assert fake.entries == {}


def test_without_keyring_library_unavailable(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)
    s = KeyringStore("x", backend=None)
    assert s.availability() == EXTRA_MISSING
    with pytest.raises(SecretStoreUnavailable) as ei:
        s.set(H, "v")
    assert str(ei.value) == EXTRA_MISSING


def test_no_install_id_reads_none_and_refuses_writes():
    s = KeyringStore(None, backend=FakeKeyring())
    assert s.service is None
    assert s.get(H) is None
    with pytest.raises(SecretStoreUnavailable, match="no install id"):
        s.set(H, "v")
    with pytest.raises(SecretStoreUnavailable, match="no install id"):
        s.delete(H)


# -- backend discovery failures are mapped, and bounded by the probe -----


def _discovery_raises(monkeypatch, exc):
    import keyring

    def boom():
        raise exc

    monkeypatch.setattr(keyring, "get_keyring", boom)


@pytest.mark.parametrize(
    "exc", [ModuleNotFoundError("nonexistent.mod"), RuntimeError("dbus SENTINEL-88"), ValueError("x")]
)
def test_discovery_error_is_a_reason_not_a_raise(monkeypatch, exc):
    pytest.importorskip("keyring")
    _discovery_raises(monkeypatch, exc)
    s = KeyringStore("x", backend=None)
    reason = s.availability()
    assert reason == f"keychain error ({type(exc).__name__})"
    for op in (lambda: s.get(H), lambda: s.set(H, "v"), lambda: s.delete(H)):
        with pytest.raises(SecretStoreUnavailable) as ei:
            op()
        assert str(ei.value) == f"keychain error ({type(exc).__name__})"
        assert "SENTINEL-88" not in repr(ei.value.__cause__)


def test_discovery_is_bounded_by_probe_timeout(monkeypatch):
    pytest.importorskip("keyring")
    import threading
    import time

    import keyring

    release = threading.Event()

    def slow():
        release.wait(5)
        return FakeKeyring()

    monkeypatch.setattr(keyring, "get_keyring", slow)
    s = KeyringStore("x", backend=None, probe_timeout=0.1)
    t0 = time.monotonic()
    try:
        assert "didn't answer" in s.availability()
    finally:
        release.set()
    assert time.monotonic() - t0 < 2


# -- low-priority (plain-text) backends are not a keychain ---------------


def _with_priority(priority, module="keyrings.alt.file"):
    cls = type("PlaintextKeyring", (FakeKeyring,), {"__module__": module, "priority": priority})
    return cls()


def test_low_priority_backend_is_unavailable():
    s = KeyringStore("x", backend=_with_priority(0.5))
    reason = s.availability()
    assert reason == "no usable OS keychain (PlaintextKeyring, priority 0.5)"
    with pytest.raises(SecretStoreUnavailable):
        s.set(H, "v")


def test_priority_one_backend_is_available():
    assert KeyringStore("x", backend=_with_priority(1)).availability() is None


def test_backend_without_priority_is_unavailable():
    plain = type("Odd", (FakeKeyring,), {"priority": None})()
    assert isinstance(KeyringStore("x", backend=plain).availability(), str)


def test_priority_that_raises_is_unavailable():
    class Broken(FakeKeyring):
        @property
        def priority(self):
            raise RuntimeError("not viable")

    assert isinstance(KeyringStore("x", backend=Broken()).availability(), str)


def test_chainer_of_low_priority_members_is_unavailable():
    chainer = type("ChainerBackend", (FakeKeyring,), {"__module__": "keyring.backends.chainer", "priority": 10})()
    chainer.backends = [_with_priority(0.5), _with_priority(0.2)]
    assert "no usable OS keychain" in KeyringStore("x", backend=chainer).availability()
    chainer.backends = [_with_priority(0.5), _with_priority(5)]
    assert KeyringStore("x", backend=chainer).availability() is None


def test_probe_thread_dying_is_not_reported_as_a_timeout():
    class Dies(FakeKeyring):
        def get_password(self, service, username):
            raise SystemExit  # a BaseException: ends the probe thread

    why = KeyringStore("abc", backend=Dies(), probe_timeout=2).availability()
    assert why == "keychain probe failed (SystemExit)"
