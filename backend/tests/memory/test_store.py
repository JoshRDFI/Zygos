import sqlite3

import pytest

from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord


def _rec(id, layer=MemoryLayer.EPISODIC, text="alpha beta", trail="t1", consolidated=False):
    return MemoryRecord(
        id=id, trail_id=trail, layer=layer, content=MemoryContent(text=text),
        importance=0.5, created_at=1.0, last_accessed=1.0, consolidated=consolidated,
    )


def test_add_then_get_is_durable_across_reopen(tmp_path):
    path = tmp_path / "m.db"
    store = MemoryStore(path)
    store.add_record(_rec("r1", text="durable text"))
    store.close()

    reopened = MemoryStore(path)  # simulates a fresh process
    got = reopened.get_record("r1")
    assert got is not None and got.content.text == "durable text"
    reopened.close()


def test_wal_mode_enabled(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    mode = store.connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    store.close()


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "m.db"
    MemoryStore(path).close()
    MemoryStore(path).close()  # must not raise on second open
    store = MemoryStore(path)
    assert store.connection.execute(
        "SELECT name FROM sqlite_master WHERE name='memory_fts'"
    ).fetchone() is not None
    store.close()


def test_records_by_layer_and_counts(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    store.add_record(_rec("e1", MemoryLayer.EPISODIC))
    store.add_record(_rec("e2", MemoryLayer.EPISODIC))
    store.add_record(_rec("s1", MemoryLayer.SEMANTIC))
    assert {r.id for r in store.records_by_layer(MemoryLayer.EPISODIC)} == {"e1", "e2"}
    assert store.counts() == {"working": 0, "episodic": 2, "semantic": 1}
    store.close()


def test_consolidate_batch_is_atomic_and_advances_state(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    store.add_record(_rec("e1", MemoryLayer.EPISODIC))
    store.add_record(_rec("e2", MemoryLayer.EPISODIC))
    assert store.pending_consolidation_count() == 2

    sem = _rec("s1", MemoryLayer.SEMANTIC, text="fact")
    store.consolidate_batch(semantic=[sem], source_ids=["e1", "e2"], at=99.0)

    assert store.pending_consolidation_count() == 0
    assert store.get_record("s1") is not None
    assert store.last_consolidated_at() == 99.0
    store.close()


def test_unconsolidated_episodic_respects_limit_and_order(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    for i in range(3):
        store.add_record(_rec(f"e{i}", MemoryLayer.EPISODIC))
    batch = store.unconsolidated_episodic(limit=2)
    assert [r.id for r in batch] == ["e0", "e1"]  # insertion order
    store.close()


def test_consolidate_batch_rolls_back_on_failure(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    store.add_record(_rec("e1", MemoryLayer.EPISODIC))
    store.add_record(_rec("e2", MemoryLayer.EPISODIC))
    # Two semantic records with the SAME id -> the second insert raises IntegrityError
    # mid-transaction, after the first was already inserted.
    dup_a = _rec("dup", MemoryLayer.SEMANTIC, text="a")
    dup_b = _rec("dup", MemoryLayer.SEMANTIC, text="b")
    with pytest.raises(sqlite3.IntegrityError):
        store.consolidate_batch(semantic=[dup_a, dup_b], source_ids=["e1", "e2"], at=42.0)
    # Everything rolled back: sources still pending, cursor untouched, no semantic rows.
    assert store.pending_consolidation_count() == 2
    assert store.last_consolidated_at() is None
    assert store.records_by_layer(MemoryLayer.SEMANTIC) == []
    assert store.get_record("dup") is None
    store.close()


def _rec_for_embedding(store, rid, text):
    """Helper to create and add a record for embedding tests."""
    r = MemoryRecord(id=rid, trail_id="t", layer=MemoryLayer.EPISODIC,
                     content=MemoryContent(text=text), importance=0.5,
                     created_at=0.0, last_accessed=0.0)
    store.add_record(r)
    return r


def test_embedding_upsert_and_model_scoped_selection(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _rec_for_embedding(store, "a", "alpha")
    _rec_for_embedding(store, "b", "beta")

    # Nothing embedded yet: both pending for model "m1".
    assert store.pending_embedding_count("m1") == 2
    assert store.embedded_count("m1") == 0
    assert {r.id for r in store.unembedded("m1", 10)} == {"a", "b"}

    store.upsert_embedding("a", "m1", 2, b"\x00\x00\x80?\x00\x00\x00\x00")  # 2 float32
    assert store.embedded_count("m1") == 1
    assert store.pending_embedding_count("m1") == 1
    assert {r.id for r in store.unembedded("m1", 10)} == {"b"}

    # A different active model treats "a" as unembedded (no cross-model reuse).
    assert {r.id for r in store.unembedded("m2", 10)} == {"a", "b"}

    # Re-embedding "a" under m1 overwrites (upsert), not duplicates.
    store.upsert_embedding("a", "m1", 2, b"\x00\x00\x00\x00\x00\x00\x80?")
    assert store.embedded_count("m1") == 1
    store.close()


def test_unembedded_respects_limit(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    for i in range(5):
        _rec_for_embedding(store, f"r{i}", f"text {i}")
    assert len(store.unembedded("m1", 2)) == 2
    store.close()
