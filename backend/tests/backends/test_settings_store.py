import logging

import pytest
from pydantic import ValidationError

from zygos.backends.settings import (
    BackendsSettings,
    LlamaCppBackend,
    OllamaBackend,
    VllmEndpoint,
    effective_args,
)
from zygos.backends.store import SqliteBackendsStore
from zygos.personalization import Personalization, SqlitePreferencesStore


def _filled() -> BackendsSettings:
    return BackendsSettings(
        ollama=OllamaBackend(base_url="http://h:11434"),
        llamacpp=LlamaCppBackend(
            server_path="/opt/llama-server",
            models_dir="/models",
            default_args="-ngl 99",
            model_args={"a.gguf": "-c 4096"},
        ),
        vllm=[VllmEndpoint(base_url="http://v:8000/v1")],
    )


def test_round_trip(tmp_path):
    store = SqliteBackendsStore(tmp_path / "p.db")
    store.set(_filled())
    assert SqliteBackendsStore(tmp_path / "p.db").get() == _filled()


def test_defaults_when_missing_and_nothing_created(tmp_path):
    assert SqliteBackendsStore(tmp_path / "p.db").get() == BackendsSettings()
    assert not (tmp_path / "p.db").exists()


def test_invalid_row_gives_defaults_and_warns(tmp_path, caplog):
    import sqlite3

    store = SqliteBackendsStore(tmp_path / "p.db")
    store.set(_filled())
    with sqlite3.connect(tmp_path / "p.db") as con:
        con.execute("UPDATE backends SET data = ? WHERE id = 1", ('{"bogus": 1}',))
    with caplog.at_level(logging.WARNING, logger="zygos.backends"):
        assert store.get() == BackendsSettings()
    assert any(r.name == "zygos.backends" for r in caplog.records)


def test_two_vllm_entries_rejected():
    with pytest.raises(ValidationError):
        BackendsSettings(vllm=[VllmEndpoint(base_url="a"), VllmEndpoint(base_url="b")])


def test_vllm_name_must_be_vllm():
    with pytest.raises(ValidationError):
        BackendsSettings(vllm=[VllmEndpoint(name="other", base_url="a")])


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        OllamaBackend(nope=1)


def test_personalization_row_untouched(tmp_path):
    db = tmp_path / "p.db"
    prefs = Personalization(user_name="Josh")
    SqlitePreferencesStore(db).set(prefs)
    SqliteBackendsStore(db).set(_filled())
    assert SqlitePreferencesStore(db).get() == prefs
    assert SqliteBackendsStore(db).get() == _filled()


def test_effective_args():
    s = LlamaCppBackend(default_args="-ngl 99", model_args={"a": "-c 1", "blank": "   ", "e": ""})
    assert effective_args(s, "a") == ("-c 1", "model")
    assert effective_args(s, "zzz") == ("-ngl 99", "default")
    assert effective_args(s, "blank") == ("-ngl 99", "default")
    assert effective_args(s, "e") == ("-ngl 99", "default")


def test_missing_table_in_shared_db_is_plain_defaults(tmp_path, caplog):
    db = tmp_path / "p.db"
    SqlitePreferencesStore(db).set(Personalization(user_name="Josh"))
    with caplog.at_level(logging.WARNING, logger="zygos.backends"):
        assert SqliteBackendsStore(db).get() == BackendsSettings()
    assert not [r for r in caplog.records if r.name == "zygos.backends"]


def test_effective_args_returns_stripped_own_text():
    s = LlamaCppBackend(model_args={"a": "  -c 1  "})
    assert effective_args(s, "a") == ("-c 1", "model")
