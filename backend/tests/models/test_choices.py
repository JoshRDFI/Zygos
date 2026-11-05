import logging
import sqlite3

import pytest
from pydantic import ValidationError

from zygos.backends.settings import BackendsSettings
from zygos.backends.store import SqliteBackendsStore
from zygos.models.choices import DefaultModel, ModelChoices, SqliteModelChoicesStore
from zygos.personalization import Personalization, SqlitePreferencesStore


def _filled() -> ModelChoices:
    return ModelChoices(default_model=DefaultModel(provider="ollama", model="qwen3:8b"))


def test_round_trip(tmp_path):
    SqliteModelChoicesStore(tmp_path / "p.db").set(_filled())
    assert SqliteModelChoicesStore(tmp_path / "p.db").get() == _filled()


def test_defaults_when_missing_and_nothing_created(tmp_path):
    assert SqliteModelChoicesStore(tmp_path / "p.db").get() == ModelChoices()
    assert not (tmp_path / "p.db").exists()


def test_missing_table_in_shared_db_is_plain_defaults(tmp_path, caplog):
    db = tmp_path / "p.db"
    SqlitePreferencesStore(db).set(Personalization(user_name="Josh"))
    with caplog.at_level(logging.WARNING, logger="zygos.models"):
        assert SqliteModelChoicesStore(db).get() == ModelChoices()
    assert not [r for r in caplog.records if r.name == "zygos.models"]


def test_invalid_row_gives_defaults_and_warns(tmp_path, caplog):
    store = SqliteModelChoicesStore(tmp_path / "p.db")
    store.set(_filled())
    with sqlite3.connect(tmp_path / "p.db") as con:
        con.execute("UPDATE model_choices SET data = ? WHERE id = 1", ('{"bogus": 1}',))
    with caplog.at_level(logging.WARNING, logger="zygos.models"):
        assert store.get() == ModelChoices()
    assert any(r.name == "zygos.models" for r in caplog.records)


def test_other_rows_untouched(tmp_path):
    db = tmp_path / "p.db"
    prefs = Personalization(user_name="Josh")
    SqlitePreferencesStore(db).set(prefs)
    SqliteBackendsStore(db).set(BackendsSettings())
    SqliteModelChoicesStore(db).set(_filled())
    assert SqlitePreferencesStore(db).get() == prefs
    assert SqliteBackendsStore(db).get() == BackendsSettings()
    assert SqliteModelChoicesStore(db).get() == _filled()


def test_frozen_and_extra_forbidden():
    with pytest.raises(ValidationError):
        ModelChoices(nope=1)
    with pytest.raises(ValidationError):
        DefaultModel(provider="a", model="b", x=1)
    d = DefaultModel(provider="a", model="b")
    with pytest.raises(ValidationError):
        d.model = "c"
