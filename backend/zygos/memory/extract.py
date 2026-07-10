"""Cheap, synchronous episodic extraction — no LLM (spec §5, Extract stage).

Importance is a heuristic over cheap signals; the deferred consolidation pass
refines it with an LLM rating.

Stability: Experimental.
"""

from __future__ import annotations

from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord


def episodic_importance(text: str, *, tool_error: bool) -> float:
    score = 0.5
    if tool_error:
        score += 0.3
    if len(text) > 200:
        score += 0.3
    return min(1.0, score)


def extract_episodic(
    *, trail_id: str, text: str, at: float, record_id: str, tool_error: bool = False
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        trail_id=trail_id,
        layer=MemoryLayer.EPISODIC,
        content=MemoryContent(text=text),
        importance=episodic_importance(text, tool_error=tool_error),
        created_at=at,
        last_accessed=at,
        consolidated=False,
    )
