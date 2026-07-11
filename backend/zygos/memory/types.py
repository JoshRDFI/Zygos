"""Memory value types — layers, modality-tagged content, records, snapshot state.

`content` is a modality-tagged structure (text-only in M4) — the seam that keeps
native multimodal from forcing a schema migration later (spec §1).

Stability: Experimental.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Modality(StrEnum):
    TEXT = "text"  # only value used in M4


class MemoryLayer(StrEnum):
    WORKING = "working"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    # procedural is a named RFC-0001 layer delegated to SkillService (M6) — not built here.


class MemoryContent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    modality: Modality = Modality.TEXT
    text: str


class MemoryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    trail_id: str
    layer: MemoryLayer
    content: MemoryContent
    importance: float = 0.5
    created_at: float
    last_accessed: float
    consolidated: bool = False
    source_trail: str | None = None


class MemoryState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pending_consolidation: int
    working_count: int
    episodic_count: int
    semantic_count: int
    last_consolidated_at: float | None
    embedded_count: int = 0
    pending_embedding: int = 0
    active_embedding_model: str | None = None
