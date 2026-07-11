import pytest

pytest.importorskip("fastembed")  # skip entirely when the `embeddings` extra is absent

from zygos.providers.embedding import Embedder  # noqa: E402
from zygos.providers.embedding_local import LocalEmbedder  # noqa: E402
from zygos.providers.types import EmbedRequest  # noqa: E402
from zygos.runtime.capabilities import Capability  # noqa: E402


def test_local_embedder_declares_capability():
    assert Capability.EMBEDDING in LocalEmbedder.capabilities


@pytest.mark.live
async def test_local_embedder_embeds_real_model():
    emb = LocalEmbedder()
    assert isinstance(emb, Embedder)
    result = await emb.embed(EmbedRequest(texts=("hello world", "a different sentence")))
    assert len(result.vectors) == 2
    assert result.dim > 0 and len(result.vectors[0]) == result.dim
    assert result.vectors[0] != result.vectors[1]
