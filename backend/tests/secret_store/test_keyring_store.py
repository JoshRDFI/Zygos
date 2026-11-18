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
