from zygos.memory.retrieve import Fts5RelevanceIndex, fts_match_query
from zygos.memory.store import MemoryStore
from zygos.memory.types import MemoryContent, MemoryLayer, MemoryRecord


def _add(store, id, text):
    store.add_record(MemoryRecord(
        id=id, trail_id="t", layer=MemoryLayer.EPISODIC,
        content=MemoryContent(text=text), created_at=1.0, last_accessed=1.0,
    ))


def test_query_matches_shared_terms(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "r1", "the quick brown fox")
    _add(store, "r2", "database backup restore")
    idx = Fts5RelevanceIndex(store.connection)
    hits = idx.query("backup", k=10)
    assert [rid for rid, _ in hits] == ["r2"]
    store.close()


def test_query_ranks_best_first_with_positive_scores(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "r1", "alpha")
    _add(store, "r2", "alpha beta gamma alpha")
    idx = Fts5RelevanceIndex(store.connection)
    hits = idx.query("alpha", k=10)
    ids = [rid for rid, _ in hits]
    assert set(ids) == {"r1", "r2"}
    assert all(0.0 < score <= 1.0 for _, score in hits)
    assert hits[0][1] == 1.0  # top hit normalized to 1.0
    store.close()


def test_query_tolerates_punctuation(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    _add(store, "r1", "revert a commit")
    idx = Fts5RelevanceIndex(store.connection)
    # Must not raise an FTS5 syntax error on punctuation / quotes.
    assert idx.query('how do I "revert"?', k=5)  # returns r1
    store.close()


def test_fts_match_query_ors_terms():
    assert fts_match_query("revert commit") == '"revert" OR "commit"'
