import asyncio
import warnings
from pathlib import Path

from zygos.config.schema import MemoryConfig, ZygosConfig
from zygos.memory.retrieve import Fts5RelevanceIndex, HybridRelevanceIndex
from zygos.memory.service import DefaultMemoryService
from zygos.memory.store import MemoryStore
from zygos.providers.fake import FakeEmbedder
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.capabilities import Capability, CapabilityRegistry


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


def test_memory_index_selects_hybrid_with_embedder(tmp_path):
    from zygos.runtime.bootstrap import _memory_index
    store = MemoryStore(tmp_path / "m.db")
    idx = _memory_index("hybrid", store, FakeEmbedder(), "fake-embed")
    assert isinstance(idx, HybridRelevanceIndex)
    store.close()


def test_memory_index_degrades_to_fts_with_warning(tmp_path):
    from zygos.runtime.bootstrap import _memory_index
    store = MemoryStore(tmp_path / "m.db")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        idx = _memory_index("hybrid", store, None, "")  # mode wants an embedder, none resolved
    assert isinstance(idx, Fts5RelevanceIndex)
    assert any("fts5" in str(w.message).lower() or "embedder" in str(w.message).lower()
               for w in caught)
    store.close()


def test_memory_index_fts5_mode_ignores_embedder(tmp_path):
    from zygos.runtime.bootstrap import _memory_index
    store = MemoryStore(tmp_path / "m.db")
    idx = _memory_index("fts5", store, None, "")
    assert isinstance(idx, Fts5RelevanceIndex)
    store.close()


def test_register_embedding_dedups_by_name():
    from zygos.runtime.bootstrap import _register_embedding
    registry = CapabilityRegistry()
    emb = FakeEmbedder(model="fake-embed")
    _register_embedding(registry, emb)
    _register_embedding(registry, emb)  # second call must NOT double-register
    bindings = registry.snapshot().bindings.get(Capability.EMBEDDING, ())
    assert len([b for b in bindings if b.provider == "fake"]) == 1


def test_build_embedder_local_without_fastembed_degrades(monkeypatch):
    # Force the ImportError branch deterministically — fastembed IS installed in .venv,
    # so we must simulate its absence rather than rely on it; this also avoids any real
    # model download (construction fails before fetching).
    import sys
    import asyncio
    import httpx
    from zygos.config.schema import ZygosConfig
    from zygos.plugins.resolver import PluginRegistry
    from zygos.runtime.bootstrap import _build_embedder
    monkeypatch.setitem(sys.modules, "fastembed", None)  # `from fastembed import ...` -> ImportError
    cfg = ZygosConfig()
    cfg.memory.retrieval_mode = "hybrid"  # backend defaults to local
    client = httpx.AsyncClient()
    try:
        embedder, model = _build_embedder(cfg, client, PluginRegistry(cfg.plugins))
        assert embedder is None
        assert model == "BAAI/bge-small-en-v1.5"
    finally:
        asyncio.run(client.aclose())


def test_build_embedder_openai_empty_model_raises():
    from zygos.config.schema import ZygosConfig
    from zygos.errors import ConfigError
    from zygos.runtime.bootstrap import _build_embedder
    from zygos.plugins.resolver import PluginRegistry
    import httpx, pytest
    cfg = ZygosConfig()
    cfg.memory.retrieval_mode = "hybrid"
    cfg.memory.embedding.backend = "openai"
    cfg.memory.embedding.model = ""  # no universal default for cloud
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ConfigError, match="model"):
            _build_embedder(cfg, client, PluginRegistry(cfg.plugins))
    finally:
        import asyncio
        asyncio.run(client.aclose())


def test_default_off_memory_is_fts5(tmp_path):
    # No retrieval_mode set -> fts5; the wired index is Fts5, identical to M4.
    db = tmp_path / "mem.db"
    assembly = build_runtime(_write_config(tmp_path, True, str(db)))
    try:
        svc = assembly.memory_service
        assert isinstance(svc._index, Fts5RelevanceIndex)  # noqa: SLF001 (wiring assertion)
        assert svc._embedder is None  # noqa: SLF001
    finally:
        asyncio.run(assembly.aclose())
