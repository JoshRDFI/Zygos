import pytest

from zygos.memory.retrieve import MemoryRetriever, RetrievalWeights
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord


class FakeIndex:
    def __init__(self, results):
        self._results = results

    async def query(self, text, *, k):
        return self._results[:k]


def _add(store, id, text, *, trail="t1", importance=0.5, created=1.0):
    store.add_record(MemoryRecord(
        id=id, trail_id=trail, layer=MemoryLayer.EPISODIC,
        content=MemoryContent(text=text), importance=importance,
        created_at=created, last_accessed=created,
    ))


@pytest.mark.asyncio
async def test_ranks_by_weighted_multifactor_score(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "r1", "aaa", importance=0.1, created=0.0)
    _add(store, "r2", "bbb", importance=0.9, created=0.0)
    # Equal relevance from the index; importance must break the tie -> r2 first.
    index = FakeIndex([("r1", 1.0), ("r2", 1.0)])
    r = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(relevance=0.0, recency=0.0, importance=1.0),
        half_life_s=100.0,
    )
    out = await r.retrieve(query="x", trail_id="t1", budget=100, scope="all")
    assert [rec.id for rec in out] == ["r2", "r1"]
    store.close()


@pytest.mark.asyncio
async def test_token_budget_caps_results(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "r1", "one two three")   # 3 tokens
    _add(store, "r2", "four five six")   # 3 tokens
    index = FakeIndex([("r1", 1.0), ("r2", 0.5)])
    r = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(relevance=1.0, recency=0.0, importance=0.0),
        half_life_s=100.0,
    )
    out = await r.retrieve(query="x", trail_id="t1", budget=3, scope="all")
    assert [rec.id for rec in out] == ["r1"]  # r2 would exceed the 3-token budget
    store.close()


@pytest.mark.asyncio
async def test_scope_filters_inside_vs_cross(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "in", "same trail", trail="t1")
    _add(store, "out", "other trail", trail="t2")
    index = FakeIndex([("in", 1.0), ("out", 1.0)])
    r = MemoryRetriever(
        store, index, clock=lambda: 0.0,
        weights=RetrievalWeights(relevance=1.0, recency=0.0, importance=0.0),
        half_life_s=100.0,
    )
    inside = await r.retrieve(query="x", trail_id="t1", budget=100, scope="inside")
    cross = await r.retrieve(query="x", trail_id="t1", budget=100, scope="cross")
    assert [rec.id for rec in inside] == ["in"]
    assert [rec.id for rec in cross] == ["out"]
    store.close()
