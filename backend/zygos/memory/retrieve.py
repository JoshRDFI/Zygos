"""Retrieval: a pluggable relevance index (FTS5 now, embedding-ready) plus
multi-factor, token-budgeted assembly (spec §4).

Stability: Experimental.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Protocol

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def fts_match_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression: OR of double-quoted alphanumeric terms.

    Quoting each term neutralizes FTS5 operators and punctuation in user text.
    """
    terms = _TOKEN.findall(text)
    return " OR ".join(f'"{t}"' for t in terms)


class RelevanceIndex(Protocol):
    def query(self, text: str, *, k: int) -> list[tuple[str, float]]:
        """Return [(record_id, relevance in (0,1])] best-first."""
        ...


class Fts5RelevanceIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    def query(self, text: str, *, k: int) -> list[tuple[str, float]]:
        match = fts_match_query(text)
        if not match:
            return []
        rows = self._conn.execute(
            "SELECT record_id FROM memory_fts WHERE memory_fts MATCH ?"
            " ORDER BY rank LIMIT ?",
            (match, k),
        ).fetchall()
        # Positional relevance: best-first, normalized so the top hit == 1.0.
        return [(row[0], 1.0 / (1.0 + i)) for i, row in enumerate(rows)]
