"""SQLite persistence for the single-row personalization preferences.

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

from pydantic import ValidationError

from zygos.personalization.types import Personalization

_log = logging.getLogger("zygos.personalization")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS personalization (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
"""


class PreferencesStore(Protocol):
    def get(self) -> Personalization: ...

    def set(self, prefs: Personalization) -> None: ...


class SqlitePreferencesStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get(self) -> Personalization:
        if not self._path.exists():
            return Personalization()
        try:
            with closing(sqlite3.connect(self._path)) as con:
                row = con.execute("SELECT data FROM personalization WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            _log.warning("personalization store unreadable (%s); using empty", exc)
            return Personalization()
        if row is None:
            return Personalization()
        try:
            return Personalization.model_validate_json(row[0])
        except ValidationError as exc:
            _log.warning("personalization row invalid (%s); using empty", exc)
            return Personalization()

    def set(self, prefs: Personalization) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as con:
            con.executescript(_SCHEMA)
            con.execute(
                "INSERT INTO personalization(id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (prefs.model_dump_json(),),
            )
            con.commit()
