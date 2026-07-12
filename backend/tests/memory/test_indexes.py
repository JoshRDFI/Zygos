import pytest

pytest.importorskip("numpy")

from zygos.memory.retrieve import (
    Fts5RelevanceIndex,
    HybridRelevanceIndex,
    VectorRelevanceIndex,
)
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord
from zygos.memory.vector_search import VectorSearch
from zygos.memory.vectors import pack
from zygos.providers.embedding import Embedder
from zygos.providers.fake import FakeEmbedder
from zygos.providers.types import EmbedRequest, EmbedResult, Usage


def _rec(store, rid, text):
    store.add_record(MemoryRecord(
        id=rid, trail_id="t", layer=MemoryLayer.EPISODIC,
        content=MemoryContent(text=text), created_at=0.0, last_accessed=0.0))


async def _embed_texts(store, emb, model, ids_texts):
    for rid, text in ids_texts:
        _rec(store, rid, text)
        result = await emb.embed(EmbedRequest(model=model, texts=(text,)))
        store.upsert_embedding(rid, model, result.dim, pack(result.vectors[0]))


class BoomEmbedder:
    name = "boom"

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        raise RuntimeError("transient embed failure")


@pytest.mark.asyncio
async def test_hybrid_surfaces_semantic_match_fts_misses(tmp_path):
    # Query shares MEANING but not words with the record. Semantic arm (FakeEmbedder
    # is deterministic-by-text) is exercised; assert the hybrid path returns hits and
    # that a pure-FTS query on the disjoint words finds nothing.
    store = MemoryStore(tmp_path / "m.db")
    emb = FakeEmbedder(dim=8, model="fake-embed")
    await _embed_texts(store, emb, "fake-embed", [("r1", "the service OOM-looped on boot")])
    fts = Fts5RelevanceIndex(store.connection)
    assert await fts.query("deployment kept crashing", k=10) == []  # no shared tokens
    hybrid = HybridRelevanceIndex(
        fts, VectorSearch(store, model="fake-embed"), emb, model="fake-embed")
    hits = await hybrid.query("the service OOM-looped on boot", k=10)  # same text -> vector match
    assert any(rid == "r1" for rid, _ in hits)
    store.close()


@pytest.mark.asyncio
async def test_hybrid_still_surfaces_exact_token_match(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    emb = FakeEmbedder(dim=8, model="fake-embed")
    await _embed_texts(store, emb, "fake-embed", [("r1", "rollback the migration")])
    hybrid = HybridRelevanceIndex(
        Fts5RelevanceIndex(store.connection),
        VectorSearch(store, model="fake-embed"), emb, model="fake-embed")
    hits = await hybrid.query("rollback", k=10)
    assert any(rid == "r1" for rid, _ in hits)
    store.close()


@pytest.mark.asyncio
async def test_hybrid_embed_failure_falls_back_to_lexical(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    emb = FakeEmbedder(dim=8, model="fake-embed")
    await _embed_texts(store, emb, "fake-embed", [("r1", "rollback the migration")])
    hybrid = HybridRelevanceIndex(
        Fts5RelevanceIndex(store.connection),
        VectorSearch(store, model="fake-embed"), BoomEmbedder(), model="fake-embed")
    hits = await hybrid.query("rollback", k=10)  # embed raises -> lexical arm only
    assert [rid for rid, _ in hits] == ["r1"]
    store.close()


@pytest.mark.asyncio
async def test_vector_mode_embed_failure_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec(store, "r1", "rollback")
    index = VectorRelevanceIndex(
        BoomEmbedder(), VectorSearch(store, model="fake-embed"), model="fake-embed")
    assert await index.query("rollback", k=10) == []
    store.close()


class ZeroVectorEmbedder:
    name = "zero"

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        return EmbedResult(vectors=(), model="fake-embed", dim=8, usage=Usage())  # empty!


@pytest.mark.asyncio
async def test_hybrid_zero_vector_reply_falls_back_to_lexical(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    emb = FakeEmbedder(dim=8, model="fake-embed")
    await _embed_texts(store, emb, "fake-embed", [("r1", "rollback the migration")])
    hybrid = HybridRelevanceIndex(
        Fts5RelevanceIndex(store.connection),
        VectorSearch(store, model="fake-embed"), ZeroVectorEmbedder(), model="fake-embed")
    hits = await hybrid.query("rollback", k=10)  # embed returns no vectors -> lexical only, no IndexError
    assert [rid for rid, _ in hits] == ["r1"]
    store.close()


@pytest.mark.asyncio
async def test_vector_mode_zero_vector_reply_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec(store, "r1", "rollback")
    index = VectorRelevanceIndex(
        ZeroVectorEmbedder(), VectorSearch(store, model="fake-embed"), model="fake-embed")
    assert await index.query("rollback", k=10) == []
    store.close()


@pytest.mark.asyncio
async def test_vector_mode_returns_normalized_semantic_hits(tmp_path):
    # vector mode returns semantic hits with the top normalized to 1.0 (relevance in (0,1]).
    store = MemoryStore(tmp_path / "m.db")
    emb = FakeEmbedder(dim=8, model="fake-embed")
    await _embed_texts(store, emb, "fake-embed", [("r1", "alpha beta"), ("r2", "gamma delta")])
    index = VectorRelevanceIndex(emb, VectorSearch(store, model="fake-embed"), model="fake-embed")
    hits = await index.query("alpha beta", k=5)  # identical text -> r1 is the strongest match
    assert hits[0][0] == "r1"
    assert hits[0][1] == 1.0
    assert all(0.0 <= score <= 1.0 for _, score in hits)
    store.close()
