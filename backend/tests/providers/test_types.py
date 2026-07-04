import pytest
from pydantic import ValidationError

from zygos.providers.types import GenerationChunk, GenerationRequest, GenerationResult, Message, Usage


def test_request_is_immutable_and_strict():
    request = GenerationRequest(messages=(Message(role="user", content="hi"),))
    assert request.model == ""
    assert request.max_tokens == 1024
    with pytest.raises(ValidationError):
        request.model = "x"  # frozen
    with pytest.raises(ValidationError):
        GenerationRequest(messages=(), bogus_field=1)


def test_router_fills_model_via_model_copy():
    request = GenerationRequest(messages=(Message(role="user", content="hi"),))
    routed = request.model_copy(update={"model": "qwen3:8b"})
    assert routed.model == "qwen3:8b"
    assert request.model == ""  # original untouched


def test_result_defaults():
    result = GenerationResult(text="ok", model="m", provider="fake")
    assert result.usage == Usage()
    assert GenerationChunk(text="a").done is False


def test_message_role_restricted():
    with pytest.raises(ValidationError):
        Message(role="tool", content="x")
