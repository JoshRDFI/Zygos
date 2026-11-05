"""SQLite persistence for the single-row model choices record (RFC-0013 §10).

Same database file as personalization and backends, own table.

A short-lived connection is opened per call: the server and CLI are separate processes
and FastAPI may call from different threads. Reading never creates the database file.

Stability: Experimental.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

_log = logging.getLogger("zygos.models")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_choices (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
"""


class DefaultModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str
    model: str


class ModelChoices(BaseModel):
    # Routing settings arrive in phase 5; extra="forbid" is relaxed then.
    model_config = ConfigDict(extra="forbid")

    default_model: DefaultModel | None = None


class ModelChoicesStore(Protocol):
    def get(self) -> ModelChoices: ...

    def set(self, choices: ModelChoices) -> None: ...


class SqliteModelChoicesStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get(self) -> ModelChoices:
        if not self._path.exists():
            return ModelChoices()
        try:
            with closing(sqlite3.connect(self._path)) as con:
                has_table = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'model_choices'"
                ).fetchone()
                if has_table is None:
                    return ModelChoices()
                row = con.execute("SELECT data FROM model_choices WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            _log.warning("model choices store unreadable (%s); using defaults", exc)
            return ModelChoices()
        if row is None:
            return ModelChoices()
        try:
            return ModelChoices.model_validate_json(row[0])
        except ValidationError as exc:
            _log.warning("model choices row invalid (%s); using defaults", exc)
            return ModelChoices()

    def set(self, choices: ModelChoices) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as con:
            con.executescript(_SCHEMA)
            con.execute(
                "INSERT INTO model_choices(id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (choices.model_dump_json(),),
            )
            con.commit()
