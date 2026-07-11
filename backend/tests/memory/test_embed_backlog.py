import pytest

from zygos.memory.retrieve import Fts5RelevanceIndex, MemoryRetriever, RetrievalWeights
from zygos.memory.service import DefaultMemoryService
from zygos.memory.store import MemoryStore
from zygos.providers.fake import FakeEmbedder
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


def _service(tmp_path, *, embedder=None, model="", ids=None):
    store = MemoryStore(tmp_path / "m.db")
    index = Fts5RelevanceIndex(store.connection)
    retriever = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(), half_life_s=100.0,
    )
    id_iter = iter(ids or [f"id{i}" for i in range(100)])
    return store, DefaultMemoryService(
        store=store, retriever=retriever, index=index,
        model_service=None, clock=lambda: 0.0, new_id=lambda: next(id_iter),
        token_budget=1000, batch_size=10,
        embedder=embedder, embedding_model=model, embed_batch_size=2,
    )


def _ctx():
    return root_context(InProcessEventBus())


async def test_embed_backlog_embeds_all_then_is_idempotent(tmp_path):
    store, svc = _service(tmp_path, embedder=FakeEmbedder(dim=4), model="m1")
    ctx = _ctx()
    for text in ("one", "two", "three"):
        svc.store(ctx, text=text)

    # store() writes NO embedding row.
    assert store.pending_embedding_count("m1") == 3
    assert store.embedded_count("m1") == 0

    n = await svc.embed_backlog(ctx)
    assert n == 3
    assert store.embedded_count("m1") == 3
    assert store.pending_embedding_count("m1") == 0

    assert await svc.embed_backlog(ctx) == 0  # idempotent: nothing new


async def test_embed_backlog_noop_without_embedder(tmp_path):
    store, svc = _service(tmp_path, embedder=None, model="m1")
    ctx = _ctx()
    svc.store(ctx, text="x")
    assert await svc.embed_backlog(ctx) == 0
    assert store.embedded_count("m1") == 0


async def test_embed_backlog_reembeds_on_model_change(tmp_path):
    store, svc = _service(tmp_path, embedder=FakeEmbedder(dim=4), model="m1")
    ctx = _ctx()
    svc.store(ctx, text="x")
    await svc.embed_backlog(ctx)
    assert store.embedded_count("m1") == 1

    _, svc2 = _service(tmp_path, embedder=FakeEmbedder(dim=4), model="m2")
    # NOTE: reuse the same db path so the record persists.
    assert await svc2.embed_backlog(ctx) == 1
    assert store.embedded_count("m2") == 1


def test_snapshot_reports_embedding_counts(tmp_path):
    store, svc = _service(tmp_path, embedder=FakeEmbedder(dim=4), model="m1")
    ctx = _ctx()
    svc.store(ctx, text="x")
    state = svc.snapshot()
    assert state.active_embedding_model == "m1"
    assert state.pending_embedding == 1
    assert state.embedded_count == 0
