import asyncio
import warnings
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from zygos.memory.retrieve import Fts5RelevanceIndex, HybridRelevanceIndex
from zygos.memory.service import DefaultMemoryService
from zygos.memory.store import MemoryStore
from zygos.memory.vector_search import VectorSearch
from zygos.providers.fake import FakeEmbedder
from zygos.providers.types import EmbedRequest, EmbedResult, Usage
from zygos.runtime.bootstrap import _memory_index, _register_embedding
from zygos.runtime.capabilities import Capability, CapabilityRegistry
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


class SpyEmbedder:
    """Records that IT (not any chat client) served the embedding — AC7 decoupling."""
    name = "spy-local"

    def __init__(self) -> None:
        self.calls = 0

    async def embed(self, request: EmbedRequest) -> EmbedResult:
        self.calls += 1
        return EmbedResult(vectors=tuple((1.0, 0.0) for _ in request.texts),
                           model="spy", dim=2, usage=Usage())


def _ctx():
    return root_context(InProcessEventBus())


# AC6 — degrade-to-FTS with one warning, no failure
def test_ac6_degrade_to_fts_no_failure(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        idx = _memory_index("hybrid", store, None, "")
    assert isinstance(idx, Fts5RelevanceIndex)
    assert len(caught) == 1
    store.close()


# AC7 — embedding served by the injected embedder, NOT a chat provider (zero chat tokens)
@pytest.mark.asyncio
async def test_ac7_embedding_decoupled_from_chat(tmp_path):
    store = MemoryStore(tmp_path / "m.db")
    spy = SpyEmbedder()
    idx = HybridRelevanceIndex(
        Fts5RelevanceIndex(store.connection),
        VectorSearch(store, model="spy"), spy, model="spy")
    svc = DefaultMemoryService(
        store=store, retriever=None, index=idx, model_service=None,
        clock=lambda: 0.0, new_id=lambda: "id", token_budget=100, batch_size=8,
        embedder=spy, embedding_model="spy", embed_batch_size=8,
    )
    ctx = _ctx()
    svc.store(ctx, text="a durable fact")
    await svc.embed_backlog(ctx)         # embeds via spy
    await svc.search("durable", k=5)      # query embed via spy
    assert spy.calls >= 2                 # every embed went through the injected embedder
    store.close()


# AC9 — EMBEDDING appears in the registry snapshot (manifest/doctor surface)
def test_ac9_embedding_registered_for_inspection():
    registry = CapabilityRegistry()
    _register_embedding(registry, FakeEmbedder(model="fake-embed"))
    bindings = registry.snapshot().bindings.get(Capability.EMBEDDING, ())
    assert any(b.provider == "fake" for b in bindings)


# AC10 — no memory embedding config -> identical to M4 (fts5, no embedder)
def test_ac10_default_off_identical_to_m4(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text("memory:\n  enabled: true\n  db_path: '%s'\n" % (tmp_path / "m.db"),
                    encoding="utf-8")
    from zygos.runtime.bootstrap import build_runtime
    assembly = build_runtime(file)
    try:
        svc = assembly.memory_service
        assert isinstance(svc._index, Fts5RelevanceIndex)  # noqa: SLF001
        assert svc._embedder is None                        # noqa: SLF001
        snap = svc.snapshot()
        assert snap.active_embedding_model is None
    finally:
        asyncio.run(assembly.aclose())
