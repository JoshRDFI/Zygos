"""Shared behavioural contract for SecretStore backends (mixin; not collected directly).

Subclass in a Test* class and provide a ``store`` fixture.
"""

import pytest

from zygos.secrets import InvalidHandle, SecretStore

H = "provider:anthropic"


class SecretStoreContract:
    def test_get_missing_returns_none(self, store):
        assert store.get(H) is None

    def test_set_then_get(self, store):
        store.set(H, "v1")
        assert store.get(H) == "v1"

    def test_set_overwrites(self, store):
        store.set(H, "v1")
        store.set(H, "v2")
        assert store.get(H) == "v2"

    def test_delete_then_get_none(self, store):
        store.set(H, "v1")
        store.delete(H)
        assert store.get(H) is None

    def test_delete_missing_is_noop(self, store):
        store.delete(H)
        assert store.get(H) is None

    @pytest.mark.parametrize("value", ["", "é ünï 😀", "line1\nline2", "a=b==", "x" * 4096])
    def test_values_round_trip_exactly(self, store, value):
        store.set(H, value)
        assert store.get(H) == value

    def test_invalid_handle_rejected(self, store):
        with pytest.raises(InvalidHandle):
            store.get("bad")
        with pytest.raises(InvalidHandle):
            store.set("bad", "v")
        with pytest.raises(InvalidHandle):
            store.delete("bad")

    def test_repr_never_contains_value(self, store):
        store.set(H, "SENTINEL-9f3a")
        assert "SENTINEL-9f3a" not in repr(store)

    def test_is_a_secret_store(self, store):
        assert isinstance(store, SecretStore)
