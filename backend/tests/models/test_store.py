import json
import logging
from datetime import UTC, datetime

from zygos.models.profile import ModelProfile, record
from zygos.models.store import ProfileStore

T = datetime(2026, 11, 4, tzinfo=UTC)


def _p(model="qwen3:8b", digest=None):
    return ModelProfile(provider="ollama", model=model, names=[model], digest=digest, values={})


def test_save_then_load_round_trips(tmp_path):
    s = ProfileStore(tmp_path)
    p = record(_p(digest="d"), "identity.family", "qwen3", "ollama", T)
    s.save(p)
    assert (tmp_path / "ollama" / "qwen3_8b.json").exists()
    s2 = ProfileStore(tmp_path)
    s2.load_all()
    assert s2.get("ollama", "qwen3:8b") == p


def test_save_keeps_user_section_edited_on_disk(tmp_path):
    s = ProfileStore(tmp_path)
    p = _p()
    s.save(p)
    f = tmp_path / "ollama" / "qwen3_8b.json"
    data = json.loads(f.read_text())
    data["user"] = {"capabilities.vision": True, "notes": "mine"}
    f.write_text(json.dumps(data))
    s.save(record(p, "capabilities.tools", True, "ollama", T))
    after = json.loads(f.read_text())
    assert after["user"] == {"capabilities.vision": True, "notes": "mine"}
    assert "capabilities.tools" in after["values"]


def test_malformed_file_is_never_overwritten(tmp_path, caplog):
    f = tmp_path / "ollama" / "qwen3_8b.json"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"{not json")
    s = ProfileStore(tmp_path)
    s.load_all()
    assert s.error_for("ollama", "qwen3_8b") is not None or s.error_for("ollama", "qwen3:8b") is not None
    with caplog.at_level(logging.WARNING, logger="zygos.models"):
        s.save(_p())
    assert f.read_bytes() == b"{not json"
    assert s.get("ollama", "qwen3:8b") is None
    assert any("zygos.models" == r.name for r in caplog.records)
    assert list(f.parent.iterdir()) == [f]  # no temp litter


def test_malformed_file_blocks_save_even_without_load(tmp_path):
    f = tmp_path / "ollama" / "qwen3_8b.json"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"{not json")
    ProfileStore(tmp_path).save(_p())  # never loaded
    assert f.read_bytes() == b"{not json"


def test_find_by_digest_and_add_name_share_one_file(tmp_path):
    s = ProfileStore(tmp_path)
    s.save(_p(digest="d"))
    found = s.find_by_digest("ollama", "d")
    assert found is not None
    s.add_name(found, "qwen3:latest")
    assert [x.name for x in (tmp_path / "ollama").iterdir()] == ["qwen3_8b.json"]
    got = s.get("ollama", "qwen3:latest")
    assert got is not None and got.names == ["qwen3:8b", "qwen3:latest"]
    s2 = ProfileStore(tmp_path)
    s2.load_all()
    assert s2.get("ollama", "qwen3:latest") is not None
    assert s2.find_by_digest("ollama", "d") is not None
