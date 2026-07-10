import pytest

from zygos.memory.retrieve import Fts5RelevanceIndex, MemoryRetriever, RetrievalWeights
from zygos.memory.service import DefaultMemoryService
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryLayer
from zygos.providers.types import GenerationResult, Usage
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class FlakyModelService:
    """Raises on the first generate() call, succeeds afterwards — simulates a crash
    mid-consolidation."""
    def __init__(self, texts, fail_first=False):
        self._texts = list(texts)
        self._fail_first = fail_first
        self.calls = 0

    def classify_task(self, prompt): return "standard"
    def select_model(self, classification=None): raise NotImplementedError
    def stream(self, ctx, request): raise NotImplementedError

    async def generate(self, ctx, request):
        self.calls += 1
        if self._fail_first and self.calls == 1:
            raise RuntimeError("simulated crash mid-consolidation")
        return GenerationResult(text=self._texts.pop(0), model="f", provider="f", usage=Usage())


def _build(path, model, ids):
    store = MemoryStore(path)
    index = Fts5RelevanceIndex(store.connection)
    retriever = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(), half_life_s=100.0,
    )
    id_iter = iter(ids)
    svc = DefaultMemoryService(
        store=store, retriever=retriever, index=index, model_service=model,
        clock=lambda: 7.0, new_id=lambda: next(id_iter), token_budget=1000, batch_size=10,
    )
    return store, svc


def _ctx():
    return root_context(InProcessEventBus())


@pytest.mark.asyncio
async def test_episodic_survives_and_resume_completes_pending(tmp_path):
    path = tmp_path / "m.db"

    # Process 1: write episodic, then a consolidation attempt that crashes.
    model1 = FlakyModelService([], fail_first=True)
    store1, svc1 = _build(path, model1, ["s1", "s2"])
    ctx1 = _ctx()
    svc1.store(ctx1, text="event one")
    svc1.store(ctx1, text="event two")
    with pytest.raises(RuntimeError):
        await svc1.flush(ctx1)
    # Nothing was consolidated (rolled back); episodic is durable.
    assert store1.pending_consolidation_count() == 2
    assert store1.records_by_layer(MemoryLayer.SEMANTIC) == []
    store1.close()  # dirty shutdown

    # Process 2: fresh store on the same file resumes and finishes the pending work.
    model2 = FlakyModelService(["derived fact"], fail_first=False)
    store2, svc2 = _build(path, model2, ["s3"])
    n = await svc2.resume(_ctx())
    assert n == 2
    assert svc2.snapshot().pending_consolidation == 0
    assert len(store2.records_by_layer(MemoryLayer.SEMANTIC)) == 1

    # resume() again is a no-op (idempotent).
    assert await svc2.resume(_ctx()) == 0
    store2.close()
