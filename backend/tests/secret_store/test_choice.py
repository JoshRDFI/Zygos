import sqlite3
import threading

import pytest

from zygos.secrets import SecretStoreUnavailable
from zygos.secrets.choice import ChoiceRecord, SqliteChoiceStore


def _rec(backend: str) -> ChoiceRecord:
    return ChoiceRecord(
        backend=backend, chosen_at="2026-11-17T00:00:00+00:00", install_id="abc"
    )


def test_no_db_file_is_no_record_and_creates_nothing(tmp_path):
    path = tmp_path / "sub" / "preferences.db"
    assert SqliteChoiceStore(path).read() is None
    assert not path.exists()
    assert not path.parent.exists()


def test_existing_db_without_table_is_no_record(tmp_path):
    path = tmp_path / "preferences.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE backends (id INTEGER PRIMARY KEY, data TEXT)")
    con.commit()
    con.close()
    assert SqliteChoiceStore(path).read() is None


def test_record_if_absent_inserts_then_keeps_first(tmp_path):
    store = SqliteChoiceStore(tmp_path / "preferences.db")
    first = store.record_if_absent(_rec("keyring"))
    second = store.record_if_absent(_rec("file"))
    assert first == _rec("keyring")
    assert second == first
    assert store.read() == first


def test_unreadable_db_raises_unavailable(tmp_path):
    path = tmp_path / "preferences.db"
    path.write_bytes(b"this is not a sqlite database" * 50)
    with pytest.raises(SecretStoreUnavailable) as ei:
        SqliteChoiceStore(path).read()
    assert str(ei.value).startswith("can't read which store holds your secrets")


def test_invalid_row_raises_unavailable(tmp_path):
    path = tmp_path / "preferences.db"
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE secrets_backend (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
    )
    con.execute("INSERT INTO secrets_backend VALUES (1, ?)", ('{"backend": 1}',))
    con.commit()
    con.close()
    with pytest.raises(SecretStoreUnavailable) as ei:
        SqliteChoiceStore(path).read()
    assert str(ei.value).startswith("can't read which store holds your secrets")


def test_concurrent_record_if_absent_agree(tmp_path):
    path = tmp_path / "preferences.db"
    results: dict[str, ChoiceRecord] = {}

    def run(name: str) -> None:
        results[name] = SqliteChoiceStore(path).record_if_absent(_rec(name))

    threads = [threading.Thread(target=run, args=(n,)) for n in ("keyring", "file")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results["keyring"] == results["file"]


# -- M4: empty fields are invalid --------------------------------------------


@pytest.mark.parametrize("field", ["backend", "chosen_at", "install_id"])
def test_choice_record_fields_must_be_non_empty(field):
    from pydantic import ValidationError

    data = {"backend": "keyring", "chosen_at": "2026-11-17T00:00:00+00:00", "install_id": "abc"}
    data[field] = ""
    with pytest.raises(ValidationError):
        ChoiceRecord(**data)


def test_stored_record_with_empty_install_id_is_unreadable(tmp_path):
    import sqlite3

    db = tmp_path / "p.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE secrets_backend (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    con.execute(
        "INSERT INTO secrets_backend VALUES (1, ?)",
        ('{"backend": "keyring", "chosen_at": "2026-11-17", "install_id": ""}',),
    )
    con.commit()
    con.close()
    with pytest.raises(SecretStoreUnavailable):
        SqliteChoiceStore(db).read()


# -- M7: filesystem errors are SecretStoreUnavailable ------------------------


def test_record_mkdir_error_is_unavailable(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    store = SqliteChoiceStore(blocker / "sub" / "p.db")
    rec = ChoiceRecord(backend="keyring", chosen_at="2026-11-17T00:00:00+00:00", install_id="a")
    with pytest.raises(SecretStoreUnavailable) as ei:
        store.record_if_absent(rec)
    assert "Error" in str(ei.value)  # names the exception type


def test_read_stat_error_is_unavailable(tmp_path, monkeypatch):
    from pathlib import Path

    def denied(self, *a, **k):
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "exists", denied)
    with pytest.raises(SecretStoreUnavailable) as ei:
        SqliteChoiceStore(tmp_path / "p.db").read()
    assert "PermissionError" in str(ei.value)
