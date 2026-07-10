import pytest

from zygos.memory.types import (
    Modality, MemoryLayer, MemoryContent, MemoryRecord, MemoryState,
)


def test_record_defaults_and_content():
    rec = MemoryRecord(
        id="r1", trail_id="t1", layer=MemoryLayer.EPISODIC,
        content=MemoryContent(text="hello"),
        created_at=1.0, last_accessed=1.0,
    )
    assert rec.content.modality is Modality.TEXT
    assert rec.content.text == "hello"
    assert rec.importance == 0.5
    assert rec.consolidated is False
    assert rec.source_trail is None


def test_record_is_frozen():
    rec = MemoryRecord(
        id="r1", trail_id="t1", layer=MemoryLayer.SEMANTIC,
        content=MemoryContent(text="x"), created_at=1.0, last_accessed=1.0,
    )
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        rec.importance = 0.9  # frozen


def test_state_shape():
    st = MemoryState(
        pending_consolidation=2, working_count=0, episodic_count=3,
        semantic_count=1, last_consolidated_at=None,
    )
    assert st.pending_consolidation == 2
    assert st.last_consolidated_at is None
