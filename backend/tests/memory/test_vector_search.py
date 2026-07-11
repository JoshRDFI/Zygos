import pytest

pytest.importorskip("numpy")  # the scan requires the `embeddings` extra

from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord
from zygos.memory.vector_search import VectorSearch
from zygos.memory.vectors import pack


def _rec(store: MemoryStore, rid: str, text: str = "x") -> None:
    store.add_record(
        MemoryRecord(
            id=rid, trail_id="t", layer=MemoryLayer.EPISODIC,
            content=MemoryContent(text=text), created_at=0.0, last_accessed=0.0,
        )
    )


def test_ranks_by_cosine_best_first(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec(store, "a"); _rec(store, "b")
    store.upsert_embedding("a", "m", 3, pack((1.0, 0.0, 0.0)))
    store.upsert_embedding("b", "m", 3, pack((0.0, 1.0, 0.0)))
    hits = VectorSearch(store, model="m").search((1.0, 0.0, 0.0), k=2)
    assert hits[0][0] == "a"
    assert hits[0][1] > hits[1][1]
    store.close()


def test_filters_to_active_model(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec(store, "a")
    store.upsert_embedding("a", "other-model", 3, pack((1.0, 0.0, 0.0)))
    assert VectorSearch(store, model="m").search((1.0, 0.0, 0.0), k=5) == []
    store.close()


def test_empty_store_returns_empty(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    assert VectorSearch(store, model="m").search((1.0,), k=5) == []
    store.close()


def test_skips_dim_mismatched_row(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec(store, "a"); _rec(store, "b")
    store.upsert_embedding("a", "m", 3, pack((1.0, 0.0, 0.0)))
    store.upsert_embedding("b", "m", 2, pack((1.0, 0.0)))  # dim disagrees with query
    hits = VectorSearch(store, model="m").search((1.0, 0.0, 0.0), k=5)
    assert [rid for rid, _ in hits] == ["a"]
    store.close()
