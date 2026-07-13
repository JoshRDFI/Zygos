import pytest
from pydantic import ValidationError

from zygos.providers.types import (
    GenerationChunk,
    GenerationRequest,
    GenerationResult,
    Message,
    ToolInvocation,
    ToolSchema,
    Usage,
)


def test_request_is_immutable_and_strict():
    request = GenerationRequest(messages=(Message(role="user", content="hi"),))
    assert request.model == ""
    assert request.max_tokens is None  # ADR-0006: default = no caller cap (provider policy applies)
    with pytest.raises(ValidationError):
        request.model = "x"  # frozen
    with pytest.raises(ValidationError):
        GenerationRequest(messages=(), bogus_field=1)


def test_max_tokens_optional_and_explicit_preserved():
    msgs = (Message(role="user", content="hi"),)
    assert GenerationRequest(messages=msgs).max_tokens is None
    assert GenerationRequest(messages=msgs, max_tokens=256).max_tokens == 256


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
        Message(role="developer", content="x")  # role stays a closed Literal; "tool" is now valid (RFC-0008)


def test_tool_schema_and_invocation_construct():
    s = ToolSchema(name="read_file", description="Read a file.", parameters={"type": "object"})
    inv = ToolInvocation(id="call_1", name="read_file", arguments={"path": "a.txt"})
    assert s.parameters == {"type": "object"}
    assert inv.id == "call_1" and inv.arguments == {"path": "a.txt"}


def test_generation_request_tool_defaults_are_empty():
    req = GenerationRequest(messages=(Message(role="user", content="hi"),))
    assert req.tools == ()
    assert req.tool_choice == "auto"


def test_generation_result_tool_defaults_are_empty():
    res = GenerationResult(text="hi", model="m", provider="fake")
    assert res.tool_calls == ()
    assert res.finish_reason == "stop"


def test_message_supports_tool_exchange():
    inv = ToolInvocation(id="call_1", name="echo", arguments={"v": "x"})
    assistant = Message(role="assistant", content="", tool_calls=(inv,))
    tool_msg = Message(role="tool", tool_call_id="call_1", content='{"echoed": "x"}')
    assert assistant.tool_calls[0].name == "echo"
    assert tool_msg.role == "tool" and tool_msg.tool_call_id == "call_1"


def test_message_content_defaults_empty():
    # An assistant turn that is only tool calls may carry no text.
    m = Message(role="assistant")
    assert m.content == ""


def test_message_still_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        Message(role="user", content="hi", bogus=1)  # extra="forbid" preserved
