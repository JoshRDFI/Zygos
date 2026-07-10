from zygos.memory.extract import extract_episodic
from zygos.memory.types import MemoryLayer


def test_builds_episodic_record_with_base_importance():
    rec = extract_episodic(trail_id="t1", text="did a thing", at=5.0, record_id="r1")
    assert rec.layer is MemoryLayer.EPISODIC
    assert rec.trail_id == "t1"
    assert rec.content.text == "did a thing"
    assert rec.created_at == 5.0 and rec.last_accessed == 5.0
    assert rec.consolidated is False
    assert rec.importance == 0.5


def test_tool_error_raises_importance():
    rec = extract_episodic(trail_id="t1", text="boom", at=1.0, record_id="r1", tool_error=True)
    assert rec.importance == 0.8


def test_importance_is_clamped_to_one():
    long_text = "x" * 250
    rec = extract_episodic(trail_id="t1", text=long_text, at=1.0, record_id="r1", tool_error=True)
    assert rec.importance == 1.0  # 0.5 + 0.3 + 0.3 = 1.1 clamped to 1.0
