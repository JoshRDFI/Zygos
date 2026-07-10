import pytest

from zygos.memory.retrieve import Fts5RelevanceIndex, MemoryRetriever, RetrievalWeights
from zygos.memory.service import DefaultMemoryService
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryLayer
from zygos.providers.types import GenerationResult, Usage
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class FakeModelService:
    def __init__(self, texts): self._texts = list(texts)
    def classify_task(self, prompt): return "standard"
    def select_model(self, classification=None): raise NotImplementedError
    def stream(self, ctx, request): raise NotImplementedError
    async def generate(self, ctx, request):
        return GenerationResult(text=self._texts.pop(0), model="f", provider="f", usage=Usage())


def _service(tmp_path, model_texts=("fact",), ids=None):
    store = MemoryStore(tmp_path / "m.db")
    index = Fts5RelevanceIndex(store.connection)
    retriever = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(relevance=1.0, recency=0.0, importance=0.0),
        half_life_s=100.0,
    )
    id_iter = iter(ids or [f"id{i}" for i in range(100)])
    return store, DefaultMemoryService(
        store=store, retriever=retriever, index=index,
        model_service=FakeModelService(model_texts),
        clock=lambda: 0.0, new_id=lambda: next(id_iter),
        token_budget=1000, batch_size=10,
    )


def _ctx():
    return root_context(InProcessEventBus())


def test_store_writes_durable_episodic_and_snapshot(tmp_path):
    store, svc = _service(tmp_path)
    ctx = _ctx()
    rec = svc.store(ctx, text="hello world")
    assert rec.layer is MemoryLayer.EPISODIC
    assert rec.trail_id == ctx.run_id  # inside-trail == execution context
    st = svc.snapshot()
    assert st.episodic_count == 1 and st.pending_consolidation == 1
    store.close()


def test_retrieve_returns_matching_records(tmp_path):
    store, svc = _service(tmp_path)
    ctx = _ctx()
    svc.store(ctx, text="database backup instructions")
    svc.store(ctx, text="unrelated content")
    out = svc.retrieve(ctx, query="backup")
    assert [r.content.text for r in out] == ["database backup instructions"]
    store.close()


@pytest.mark.asyncio
async def test_summarize_consolidates_into_semantic(tmp_path):
    store, svc = _service(tmp_path, model_texts=["a durable fact"])
    ctx = _ctx()
    svc.store(ctx, text="event one")
    n = await svc.summarize(ctx)
    assert n == 1
    assert svc.snapshot().semantic_count == 1
    assert svc.snapshot().pending_consolidation == 0
    store.close()


def test_store_rejects_non_episodic_layer(tmp_path):
    store, svc = _service(tmp_path)
    ctx = _ctx()
    with pytest.raises(ValueError):
        svc.store(ctx, text="x", layer=MemoryLayer.SEMANTIC)
    store.close()
