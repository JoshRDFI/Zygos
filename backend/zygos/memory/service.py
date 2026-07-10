"""MemoryService — RFC-0001 §2 surface over the 4-stage loop (spec §2).

store/search/retrieve/snapshot are cheap & synchronous. summarize/flush/resume are
async (they drive the LLM-backed consolidation). One consolidation engine, three
entry points (spec §2).

Stability: Experimental.
"""

from __future__ import annotations

from typing import Callable, Protocol

from zygos.memory.consolidate import consolidate
from zygos.memory.extract import extract_episodic
from zygos.memory.retrieve import MemoryRetriever, RelevanceIndex, Scope
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryLayer, MemoryRecord, MemoryState
from zygos.runtime.context import ExecutionContext
from zygos.services.model import ModelService


class MemoryService(Protocol):
    def store(self, ctx: ExecutionContext, *, text: str,
              layer: MemoryLayer = MemoryLayer.EPISODIC,
              tool_error: bool = False) -> MemoryRecord: ...

    def retrieve(self, ctx: ExecutionContext, *, query: str,
                 budget: int | None = None, scope: Scope = "all",
                 k: int = 20) -> list[MemoryRecord]: ...

    def search(self, query: str, *, k: int = 10) -> list[MemoryRecord]: ...

    async def summarize(self, ctx: ExecutionContext) -> int: ...

    async def flush(self, ctx: ExecutionContext) -> int: ...

    async def resume(self, ctx: ExecutionContext) -> int: ...

    def snapshot(self) -> MemoryState: ...


class DefaultMemoryService:
    def __init__(
        self,
        *,
        store: MemoryStore,
        retriever: MemoryRetriever,
        index: RelevanceIndex,
        model_service: ModelService,
        clock: Callable[[], float],
        new_id: Callable[[], str],
        token_budget: int,
        batch_size: int,
    ) -> None:
        self._store = store
        self._retriever = retriever
        self._index = index
        self._model = model_service
        self._clock = clock
        self._new_id = new_id
        self._budget = token_budget
        self._batch = batch_size

    # --- Extract (cheap, synchronous, durable) ---
    def store(self, ctx, *, text, layer=MemoryLayer.EPISODIC, tool_error=False):
        record = extract_episodic(
            trail_id=ctx.run_id, text=text, at=self._clock(),
            record_id=self._new_id(), tool_error=tool_error,
        )
        self._store.add_record(record)
        return record

    # --- Retrieve + Apply ---
    def retrieve(self, ctx, *, query, budget=None, scope="all", k=20):
        return self._retriever.retrieve(
            query=query, trail_id=ctx.run_id,
            budget=budget if budget is not None else self._budget,
            scope=scope, k=k,
        )

    def search(self, query, *, k=10):
        hits = self._index.query(query, k=k)
        records = [self._store.get_record(rid) for rid, _ in hits]
        return [r for r in records if r is not None]

    # --- Update (deferred consolidation; one engine, three entry points) ---
    async def summarize(self, ctx):
        return await self._consolidate(ctx, drain=False)

    async def flush(self, ctx):
        return await self._consolidate(ctx, drain=True)

    async def resume(self, ctx):
        return await self._consolidate(ctx, drain=True)

    async def _consolidate(self, ctx, *, drain):
        return await consolidate(
            store=self._store, model_service=self._model, ctx=ctx,
            clock=self._clock, new_id=self._new_id, batch_size=self._batch, drain=drain,
        )

    # --- Observability (pull-based) ---
    def snapshot(self):
        counts = self._store.counts()
        return MemoryState(
            pending_consolidation=self._store.pending_consolidation_count(),
            working_count=counts["working"],
            episodic_count=counts["episodic"],
            semantic_count=counts["semantic"],
            last_consolidated_at=self._store.last_consolidated_at(),
        )
