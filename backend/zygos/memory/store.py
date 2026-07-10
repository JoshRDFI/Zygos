"""SQLite/WAL persistence for memory records + FTS5 index + consolidation cursor.

Episodic writes commit immediately (durable-on-write). `consolidate_batch` folds a
derived semantic set and marks its sources in a single transaction, so an interrupted
consolidation rolls back cleanly and is safe to redo (spec §3, §5).

Stability: Experimental.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_record (
    id            TEXT PRIMARY KEY,
    trail_id      TEXT NOT NULL,
    layer         TEXT NOT NULL,
    modality      TEXT NOT NULL,
    text          TEXT NOT NULL,
    importance    REAL NOT NULL,
    created_at    REAL NOT NULL,
    last_accessed REAL NOT NULL,
    consolidated  INTEGER NOT NULL DEFAULT 0,
    source_trail  TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(record_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS consolidation_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_consolidated_at REAL
);
INSERT OR IGNORE INTO consolidation_state(id, last_consolidated_at) VALUES (1, NULL);
"""


class MemoryStore:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._conn

    def _insert_record(self, cur: sqlite3.Cursor, rec: MemoryRecord) -> None:
        cur.execute(
            "INSERT INTO memory_record"
            "(id, trail_id, layer, modality, text, importance, created_at,"
            " last_accessed, consolidated, source_trail)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rec.id, rec.trail_id, rec.layer.value, rec.content.modality.value,
             rec.content.text, rec.importance, rec.created_at, rec.last_accessed,
             int(rec.consolidated), rec.source_trail),
        )
        cur.execute(
            "INSERT INTO memory_fts(record_id, text) VALUES (?, ?)",
            (rec.id, rec.content.text),
        )

    def add_record(self, record: MemoryRecord) -> None:
        with self._conn:  # transaction: commit on success, rollback on error
            self._insert_record(self._conn.cursor(), record)

    def consolidate_batch(
        self, *, semantic: list[MemoryRecord], source_ids: list[str], at: float
    ) -> None:
        with self._conn:  # single atomic transaction
            cur = self._conn.cursor()
            for rec in semantic:
                self._insert_record(cur, rec)
            cur.executemany(
                "UPDATE memory_record SET consolidated=1 WHERE id=?",
                [(sid,) for sid in source_ids],
            )
            cur.execute(
                "UPDATE consolidation_state SET last_consolidated_at=? WHERE id=1", (at,)
            )

    @staticmethod
    def _row_to_record(row: tuple) -> MemoryRecord:
        (id_, trail_id, layer, modality, text, importance, created_at,
         last_accessed, consolidated, source_trail) = row
        return MemoryRecord(
            id=id_, trail_id=trail_id, layer=MemoryLayer(layer),
            content=MemoryContent(modality=modality, text=text),
            importance=importance, created_at=created_at, last_accessed=last_accessed,
            consolidated=bool(consolidated), source_trail=source_trail,
        )

    _COLS = ("id, trail_id, layer, modality, text, importance, created_at, "
             "last_accessed, consolidated, source_trail")

    def get_record(self, record_id: str) -> MemoryRecord | None:
        row = self._conn.execute(
            f"SELECT {self._COLS} FROM memory_record WHERE id=?", (record_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def records_by_layer(self, layer: MemoryLayer) -> list[MemoryRecord]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM memory_record WHERE layer=? ORDER BY rowid",
            (layer.value,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def unconsolidated_episodic(self, *, limit: int) -> list[MemoryRecord]:
        rows = self._conn.execute(
            f"SELECT {self._COLS} FROM memory_record"
            " WHERE layer='episodic' AND consolidated=0 ORDER BY rowid LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def counts(self) -> dict[str, int]:
        result = {"working": 0, "episodic": 0, "semantic": 0}
        for layer, n in self._conn.execute(
            "SELECT layer, COUNT(*) FROM memory_record GROUP BY layer"
        ).fetchall():
            result[layer] = n
        return result

    def pending_consolidation_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM memory_record WHERE layer='episodic' AND consolidated=0"
        ).fetchone()[0]

    def last_consolidated_at(self) -> float | None:
        return self._conn.execute(
            "SELECT last_consolidated_at FROM consolidation_state WHERE id=1"
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()
