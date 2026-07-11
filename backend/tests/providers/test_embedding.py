import pytest

from zygos.providers.embedding import Embedder
from zygos.providers.types import EmbedRequest, EmbedResult, Usage


def test_embed_request_and_result_are_frozen_and_strict():
    req = EmbedRequest(model="m", texts=("a", "b"))
    assert req.texts == ("a", "b")
    with pytest.raises(Exception):
        req.texts = ("c",)  # frozen
    with pytest.raises(Exception):
        EmbedRequest(model="m", texts=("a",), extra="x")  # extra forbidden

    res = EmbedResult(vectors=((0.1, 0.2), (0.3, 0.4)), model="m", dim=2)
    assert res.dim == 2
    assert res.usage == Usage()
    with pytest.raises(Exception):
        res.dim = 3  # frozen


def test_embedder_is_runtime_checkable():
    class Good:
        name = "good"
        async def embed(self, request: EmbedRequest) -> EmbedResult:
            return EmbedResult(vectors=(), model="m", dim=0)

    class Bad:
        name = "bad"
        async def generate(self, request):  # not an embedder
            return None

    assert isinstance(Good(), Embedder)
    assert not isinstance(Bad(), Embedder)
