"""Retrieval: a pluggable relevance index (FTS5 now, embedding-ready) plus
multi-factor, token-budgeted assembly (spec §4).

Stability: Experimental.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Callable, Literal, Protocol

from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryRecord

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def fts_match_query(text: str) -> str:
    """Build a safe FTS5 MATCH expression: OR of double-quoted alphanumeric terms.

    Quoting each term neutralizes FTS5 operators and punctuation in user text.
    """
    terms = _TOKEN.findall(text)
    return " OR ".join(f'"{t}"' for t in terms)


def rrf_fuse(
    lexical: list[tuple[str, float]],
    semantic: list[tuple[str, float]],
    *,
    k: int,
    K: int = 60,
) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion (RFC-0006 §5): fuse two ranked id lists by RANK, not
    score. score(id) = Σ_arm 1/(K + rank_arm(id)); scale-agnostic, no per-corpus
    tuning. Normalized so the top result is 1.0; best-first, capped at k.
    """
    scores: dict[str, float] = {}
    for arm in (lexical, semantic):
        for rank, (record_id, _score) in enumerate(arm):
            scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (K + rank)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return []
    top = ranked[0][1]
    return [(record_id, s / top) for record_id, s in ranked[:k]]


class RelevanceIndex(Protocol):
    async def query(self, text: str, *, k: int) -> list[tuple[str, float]]:
        """Return [(record_id, relevance in (0,1])] best-first."""
        ...


class Fts5RelevanceIndex:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._conn = connection

    async def query(self, text: str, *, k: int) -> list[tuple[str, float]]:
        match = fts_match_query(text)
        if not match:
            return []
        rows = self._conn.execute(
            "SELECT record_id FROM memory_fts WHERE memory_fts MATCH ?"
            " ORDER BY rank LIMIT ?",
            (match, k),
        ).fetchall()
        # M4 stand-in: positional relevance (rank order), NOT BM25 magnitude —
        # the embedding/hybrid increment replaces this. Normalized so the top hit == 1.0.
        return [(row[0], 1.0 / (1.0 + i)) for i, row in enumerate(rows)]


# --- Multi-factor, token-budgeted retrieval assembly ---

Scope = Literal["inside", "cross", "all"]


@dataclass(frozen=True)
class RetrievalWeights:
    relevance: float = 0.5
    recency: float = 0.2
    importance: float = 0.3


def _estimate_tokens(text: str) -> int:
    # M4 approximation: word count as a token proxy (no tokenizer dependency).
    return len(text.split())


class MemoryRetriever:
    def __init__(
        self,
        store: MemoryStore,
        index: RelevanceIndex,
        *,
        clock: Callable[[], float],
        weights: RetrievalWeights,
        half_life_s: float,
    ) -> None:
        self._store = store
        self._index = index
        self._clock = clock
        self._w = weights
        self._half_life = half_life_s

    def _recency(self, record: MemoryRecord) -> float:
        age = max(0.0, self._clock() - record.last_accessed)
        return 1.0 / (1.0 + age / self._half_life)

    def _in_scope(self, record: MemoryRecord, trail_id: str, scope: Scope) -> bool:
        if scope == "inside":
            return record.trail_id == trail_id
        if scope == "cross":
            return record.trail_id != trail_id
        return True

    async def retrieve(
        self, *, query: str, trail_id: str, budget: int, scope: Scope, k: int = 20
    ) -> list[MemoryRecord]:
        hits = await self._index.query(query, k=k)
        scored: list[tuple[float, MemoryRecord]] = []
        for record_id, relevance in hits:
            record = self._store.get_record(record_id)
            if record is None or not self._in_scope(record, trail_id, scope):
                continue
            score = (
                self._w.relevance * relevance
                + self._w.recency * self._recency(record)
                + self._w.importance * record.importance
            )
            scored.append((score, record))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        selected: list[MemoryRecord] = []
        spent = 0
        for _, record in scored:
            cost = _estimate_tokens(record.content.text)
            if spent + cost > budget:
                continue
            selected.append(record)
            spent += cost
        return selected
