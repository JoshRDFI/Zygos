import logging
import sqlite3

import pytest
from pydantic import ValidationError

from zygos.config.schema import ZygosConfig
from zygos.personalization import (
    FIELD_MAX_LENGTHS,
    PERSONALIZATION_FIELDS,
    Personalization,
    SqlitePreferencesStore,
)


def _filled() -> Personalization:
    return Personalization(
        user_name="Josh", assistant_name="Rommie", tone="concise", persona="Dry wit."
    )


def test_empty_store_returns_all_none(tmp_path):
    got = SqlitePreferencesStore(tmp_path / "p.db").get()
    assert got == Personalization()
    assert got.is_empty


def test_get_on_missing_file_does_not_create_it(tmp_path):
    SqlitePreferencesStore(tmp_path / "p.db").get()
    assert not (tmp_path / "p.db").exists()


def test_set_get_round_trip(tmp_path):
    store = SqlitePreferencesStore(tmp_path / "p.db")
    store.set(_filled())
    assert store.get() == _filled()


def test_set_creates_parent_dirs(tmp_path):
    store = SqlitePreferencesStore(tmp_path / "a" / "b" / "p.db")
    store.set(_filled())
    assert store.get() == _filled()


def test_second_instance_sees_write(tmp_path):
    a = SqlitePreferencesStore(tmp_path / "p.db")
    b = SqlitePreferencesStore(tmp_path / "p.db")
    a.set(_filled())
    assert b.get() == _filled()


def test_overwrite_upserts(tmp_path):
    store = SqlitePreferencesStore(tmp_path / "p.db")
    store.set(_filled())
    store.set(Personalization(user_name="Ann"))
    assert store.get() == Personalization(user_name="Ann")


def test_clear_by_setting_empty(tmp_path):
    store = SqlitePreferencesStore(tmp_path / "p.db")
    store.set(_filled())
    store.set(Personalization())
    assert store.get().is_empty


def test_corrupt_row_degrades_to_empty(tmp_path, caplog):
    path = tmp_path / "p.db"
    store = SqlitePreferencesStore(path)
    store.set(_filled())
    con = sqlite3.connect(path)
    con.execute("UPDATE personalization SET data = 'not json' WHERE id = 1")
    con.commit()
    con.close()
    with caplog.at_level(logging.WARNING, logger="zygos.personalization"):
        got = store.get()
    assert got.is_empty
    assert any(r.name == "zygos.personalization" and r.levelno == logging.WARNING
               for r in caplog.records)


def test_whitespace_becomes_none():
    p = Personalization(user_name="  ", tone=" calm ")
    assert p.user_name is None
    assert p.tone == "calm"


def test_over_bound_rejected():
    with pytest.raises(ValidationError):
        Personalization(user_name="x" * 65)
    with pytest.raises(ValidationError):
        Personalization(persona="x" * 601)
    Personalization(user_name="x" * 64, persona="x" * 600)


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        Personalization(nickname="J")


def test_frozen():
    with pytest.raises(ValidationError):
        _filled().user_name = "x"


def test_field_bounds_and_order():
    assert PERSONALIZATION_FIELDS == (
        "user_name", "address", "pronouns", "assistant_name", "tone", "persona"
    )
    assert FIELD_MAX_LENGTHS == {
        "user_name": 64, "address": 64, "pronouns": 64,
        "assistant_name": 64, "tone": 120, "persona": 600,
    }


def test_config_default_db_path():
    assert ZygosConfig().personalization.db_path == ".zygos/preferences.db"
