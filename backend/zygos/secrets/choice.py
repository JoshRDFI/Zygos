"""Single-row record of which secret store this install chose.

Lives in the preferences database (own table). Unlike the backends store, a SQLite
error or an invalid row raises ``SecretStoreUnavailable`` rather than reading as empty:
guessing the wrong store would hide existing secrets. An absent file or table is a
plain "no record". Reading never creates the database file.

Stability: Experimental.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zygos.secrets.types import SecretStoreUnavailable

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS secrets_backend ("
    "id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL)"
)
_UNREADABLE = "can't read which store holds your secrets"


class ChoiceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    backend: str = Field(min_length=1)
    chosen_at: str = Field(min_length=1)  # ISO-8601 UTC
    install_id: str = Field(min_length=1)


def _unavailable(exc: Exception) -> SecretStoreUnavailable:
    return SecretStoreUnavailable(f"{_UNREADABLE} ({type(exc).__name__})")


def _parse(data: str) -> ChoiceRecord:
    try:
        return ChoiceRecord.model_validate_json(data)
    except ValidationError as exc:
        raise _unavailable(exc) from None


class SqliteChoiceStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def read(self) -> ChoiceRecord | None:
        try:
            if not self._path.exists():
                return None
        except OSError as exc:
            raise _unavailable(exc) from None
        try:
            with closing(sqlite3.connect(self._path, timeout=5)) as con:
                has_table = con.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'secrets_backend'"
                ).fetchone()
                if has_table is None:
                    return None
                row = con.execute(
                    "SELECT data FROM secrets_backend WHERE id = 1"
                ).fetchone()
        except sqlite3.Error as exc:
            raise _unavailable(exc) from None
        return None if row is None else _parse(row[0])

    def record_if_absent(self, record: ChoiceRecord) -> ChoiceRecord:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecretStoreUnavailable(
                f"can't create the preferences directory ({type(exc).__name__})"
            ) from None
        try:
            con = sqlite3.connect(self._path, timeout=5, isolation_level=None)
            with closing(con):
                con.execute("BEGIN IMMEDIATE")
                try:
                    con.execute(_SCHEMA)
                    con.execute(
                        "INSERT OR IGNORE INTO secrets_backend(id, data) VALUES (1, ?)",
                        (record.model_dump_json(),),
                    )
                    row = con.execute(
                        "SELECT data FROM secrets_backend WHERE id = 1"
                    ).fetchone()
                    con.execute("COMMIT")
                except BaseException:
                    con.execute("ROLLBACK")
                    raise
        except sqlite3.Error as exc:
            raise _unavailable(exc) from None
        return _parse(row[0])
