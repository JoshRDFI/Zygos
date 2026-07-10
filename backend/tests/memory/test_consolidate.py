import pytest

from zygos.memory.consolidate import consolidate
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord
from zygos.providers.types import GenerationResult, Usage
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class FakeModelService:
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def classify_task(self, prompt): return "standard"
    def select_model(self, classification=None): raise NotImplementedError
    def stream(self, ctx, request): raise NotImplementedError

    async def generate(self, ctx, request):
        self.calls += 1
        return GenerationResult(
            text=self._texts.pop(0), model="fake", provider="fake", usage=Usage(),
        )


def _ctx():
    return root_context(InProcessEventBus())


def _episodic(store, ids):
    for i in ids:
        store.add_record(MemoryRecord(
            id=i, trail_id="t1", layer=MemoryLayer.EPISODIC,
            content=MemoryContent(text=f"event {i}"), created_at=1.0, last_accessed=1.0,
        ))


@pytest.mark.asyncio
async def test_consolidation_derives_semantic_and_marks_sources(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _episodic(store, ["e1", "e2"])
    ids = iter(["s1", "s2"])
    model = FakeModelService(["user prefers dark mode\nuser is a vegetarian"])

    n = await consolidate(
        store=store, model_service=model, ctx=_ctx(),
        clock=lambda: 42.0, new_id=lambda: next(ids),
        batch_size=10, drain=True,
    )

    assert n == 2  # two episodic folded
    semantic = store.records_by_layer(MemoryLayer.SEMANTIC)
    assert {r.content.text for r in semantic} == {"user prefers dark mode", "user is a vegetarian"}
    assert all(r.source_trail == "t1" for r in semantic)
    assert store.pending_consolidation_count() == 0
    assert store.last_consolidated_at() == 42.0
    store.close()


@pytest.mark.asyncio
async def test_consolidation_is_idempotent(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _episodic(store, ["e1"])
    ids = iter(["s1"])
    model = FakeModelService(["a fact"])
    await consolidate(store=store, model_service=model, ctx=_ctx(),
                      clock=lambda: 1.0, new_id=lambda: next(ids),
                      batch_size=10, drain=True)
    # Second run: nothing pending -> no LLM call, no new semantic records.
    n = await consolidate(store=store, model_service=model, ctx=_ctx(),
                          clock=lambda: 2.0, new_id=lambda: "unused",
                          batch_size=10, drain=True)
    assert n == 0
    assert model.calls == 1
    assert len(store.records_by_layer(MemoryLayer.SEMANTIC)) == 1
    store.close()


@pytest.mark.asyncio
async def test_drain_false_processes_one_batch_only(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _episodic(store, ["e1", "e2", "e3"])
    ids = iter(["s1", "s2"])
    model = FakeModelService(["fact one", "fact two"])
    n = await consolidate(store=store, model_service=model, ctx=_ctx(),
                          clock=lambda: 1.0, new_id=lambda: next(ids),
                          batch_size=2, drain=False)
    assert n == 2  # only the first batch of 2
    assert store.pending_consolidation_count() == 1
    store.close()
