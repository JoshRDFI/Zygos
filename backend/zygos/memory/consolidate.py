"""Deferred episodic->semantic consolidation (spec §5, Update stage).

Cheap-write is elsewhere; this is the expensive, off-critical-path pass. Each batch
makes ONE LLM call (no DB lock held across it), then commits the derived semantic
records and the source-marking in a single store transaction — so it is atomic,
idempotent (only `consolidated=0` rows), and resumable (a crash before commit
rolls back and is redone).

Stability: Experimental.
"""

from __future__ import annotations

from typing import Callable

from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService

_PROMPT = (
    "Extract durable, reusable facts from the interaction events below. "
    "Output one fact per line, no numbering, no commentary. Omit ephemeral details.\n\n"
    "Events:\n{events}"
)


async def _derive_semantic(
    ctx: ExecutionContext,
    model_service: ModelService,
    batch: list[MemoryRecord],
    *,
    at: float,
    new_id: Callable[[], str],
    trail_id: str,
) -> list[MemoryRecord]:
    events = "\n".join(f"- {r.content.text}" for r in batch)
    request = GenerationRequest(
        messages=(Message(role="user", content=_PROMPT.format(events=events)),),
    )
    result = await model_service.generate(ctx, request)
    facts = [line.strip() for line in result.text.splitlines() if line.strip()]
    return [
        MemoryRecord(
            id=new_id(), trail_id=trail_id, layer=MemoryLayer.SEMANTIC,
            content=MemoryContent(text=fact), importance=0.6,
            created_at=at, last_accessed=at, consolidated=True, source_trail=trail_id,
        )
        for fact in facts
    ]


async def consolidate(
    *,
    store: MemoryStore,
    model_service: ModelService,
    ctx: ExecutionContext,
    clock: Callable[[], float],
    new_id: Callable[[], str],
    batch_size: int,
    drain: bool,
) -> int:
    folded = 0
    while True:
        batch = store.unconsolidated_episodic(limit=batch_size)
        if not batch:
            break
        at = clock()
        trail_id = batch[0].trail_id
        semantic = await _derive_semantic(
            ctx, model_service, batch, at=at, new_id=new_id, trail_id=trail_id
        )
        store.consolidate_batch(
            semantic=semantic, source_ids=[r.id for r in batch], at=at
        )
        folded += len(batch)
        if not drain:
            break
    return folded
