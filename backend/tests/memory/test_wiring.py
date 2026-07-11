import asyncio
from pathlib import Path

from zygos.config.schema import MemoryConfig, ZygosConfig
from zygos.memory.service import DefaultMemoryService
from zygos.runtime.bootstrap import build_runtime


def test_memory_config_defaults():
    cfg = ZygosConfig()
    assert cfg.memory.enabled is False
    assert cfg.memory.db_path == ".zygos/memory.db"
    assert cfg.memory.token_budget == 2000
    assert cfg.memory.retrieval_weights.relevance == 0.5


def _write_config(tmp_path: Path, enabled: bool, db_path: str) -> Path:
    file = tmp_path / "config.yaml"
    file.write_text(
        "memory:\n"
        f"  enabled: {str(enabled).lower()}\n"
        f"  db_path: '{db_path}'\n",
        encoding="utf-8",
    )
    return file


def test_bootstrap_wires_memory_service_when_enabled(tmp_path: Path):
    db = tmp_path / "mem.db"
    assembly = build_runtime(_write_config(tmp_path, True, str(db)))
    try:
        assert isinstance(assembly.memory_service, DefaultMemoryService)
        assert db.exists()  # store constructed + migrated at bootstrap
    finally:
        asyncio.run(assembly.aclose())


def test_bootstrap_omits_memory_service_when_disabled(tmp_path: Path):
    assembly = build_runtime(_write_config(tmp_path, False, str(tmp_path / "mem.db")))
    try:
        assert assembly.memory_service is None
    finally:
        asyncio.run(assembly.aclose())


def test_memory_embedding_defaults():
    cfg = MemoryConfig()
    assert cfg.retrieval_mode == "fts5"
    assert cfg.embedding.backend == "local"
    assert cfg.embedding.model == ""
    assert cfg.embed_batch_size == 32


def test_retrieval_mode_rejects_unknown():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        MemoryConfig(retrieval_mode="semantic")  # not one of fts5|vector|hybrid
