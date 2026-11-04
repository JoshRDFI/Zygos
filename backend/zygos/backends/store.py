"""SQLite persistence for the single-row backends settings record.

Same database file as personalization, own table.

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

from zygos.backends.settings import BackendsSettings

_log = logging.getLogger("zygos.backends")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS backends (
    id   INTEGER PRIMARY KEY CHECK (id = 1),
    data TEXT NOT NULL
);
"""


class BackendsStore(Protocol):
    def get(self) -> BackendsSettings: ...

    def set(self, settings: BackendsSettings) -> None: ...


class SqliteBackendsStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get(self) -> BackendsSettings:
        if not self._path.exists():
            return BackendsSettings()
        try:
            with closing(sqlite3.connect(self._path)) as con:
                has_table = con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'backends'"
                ).fetchone()
                if has_table is None:
                    return BackendsSettings()
                row = con.execute("SELECT data FROM backends WHERE id = 1").fetchone()
        except sqlite3.Error as exc:
            _log.warning("backends store unreadable (%s); using empty", exc)
            return BackendsSettings()
        if row is None:
            return BackendsSettings()
        try:
            return BackendsSettings.model_validate_json(row[0])
        except ValidationError as exc:
            _log.warning("backends row invalid (%s); using empty", exc)
            return BackendsSettings()

    def set(self, settings: BackendsSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as con:
            con.executescript(_SCHEMA)
            con.execute(
                "INSERT INTO backends(id, data) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
                (settings.model_dump_json(),),
            )
            con.commit()
