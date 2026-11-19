"""Tool contract: JSON-Schema input tools (RFC-0015 phase 1a)."""

import pytest
from pydantic import BaseModel, ValidationError

from zygos.agent.schema import check_input_schema, tool_schema
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools import BaseTool, ToolCall, ToolContext, ToolMeta, ToolService

SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}


class _In(BaseModel):
    x: int


def test_meta_requires_exactly_one_input_kind():
    with pytest.raises(ValidationError):
        ToolMeta(name="t", description="d", input_model=_In, input_schema=SCHEMA)
    with pytest.raises(ValidationError):
        ToolMeta(name="t", description="d")
    m = ToolMeta(name="t", description="d", input_schema=SCHEMA, server="s", server_tool="x")
    assert (m.server, m.server_tool) == ("s", "x")
    assert ToolMeta(name="t", description="d", input_model=_In).server is None


def test_schema_tool_offered_as_given():
    meta = ToolMeta(name="t", description="d", input_schema=SCHEMA)
    assert tool_schema(meta).parameters == SCHEMA


def test_draft07_definitions_inlined():
    schema = {
        "type": "object",
        "properties": {"a": {"$ref": "#/definitions/A"}},
        "definitions": {"A": {"type": "string"}},
    }
    params = tool_schema(ToolMeta(name="t", description="d", input_schema=schema)).parameters
    assert params["properties"]["a"] == {"type": "string"}
    assert "definitions" not in params


def test_check_input_schema_reasons():
    assert check_input_schema({"type": "string"}) is not None
    assert check_input_schema({"properties": {}}) is not None
    cyclic = {
        "type": "object",
        "properties": {"a": {"$ref": "#/$defs/A"}},
        "$defs": {"A": {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}}},
    }
    assert check_input_schema(cyclic) is not None
    dangling = {"type": "object", "properties": {"a": {"$ref": "#/$defs/Nope"}}}
    assert check_input_schema(dangling) is not None
    assert check_input_schema(SCHEMA) is None


class _Echo(BaseTool):
    meta = ToolMeta(name="echo", description="d", input_schema=SCHEMA)

    async def execute(self, input, ctx: ToolContext):
        return input


class _Named(BaseTool):
    def __init__(self, name: str) -> None:
        self.meta = ToolMeta(name=name, description=name, input_schema=SCHEMA)

    async def execute(self, input, ctx: ToolContext):
        return input


async def test_schema_tool_gets_raw_args():
    svc = ToolService()
    svc.register(_Echo())
    res = await svc.execute(ToolCall(tool="echo", args={"q": 1}), root_context(InProcessEventBus()))
    assert res.ok and res.output == {"q": 1}


def test_unregister_and_dynamic_tools():
    svc = ToolService()
    svc.register(_Named("builtin"))
    svc.set_dynamic_tools([_Named("a"), _Named("b")])
    names = lambda: {m.name for m in svc.snapshot().registered}
    assert names() == {"builtin", "a", "b"}
    svc.set_dynamic_tools([_Named("b2")])
    assert names() == {"builtin", "b2"}
    svc.set_dynamic_tools([_Named("builtin"), _Named("c")])
    assert names() == {"builtin", "c"}
    assert svc._registry.get("builtin").meta.description == "builtin"  # built-in kept
    svc._registry.unregister("absent")  # no error


@pytest.mark.parametrize("ref", [5, None, ["#/$defs/A"], "http://x/y#/$defs/A", "#/properties/q",
                                 "A", "#/$defs/A/properties/x"])
def test_check_input_schema_bad_refs_give_reason(ref):
    schema = {"type": "object", "properties": {"a": {"$ref": ref}},
              "$defs": {"A": {"type": "string"}}}
    assert isinstance(check_input_schema(schema), str)


def test_check_input_schema_malformed_never_raises():
    assert check_input_schema("nope") is not None
    assert check_input_schema({"type": "object", "$defs": 5, "properties": {}}) is not None
    # a non-dict definition body must not raise either (reason or None, both acceptable)
    check_input_schema({"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}},
                        "$defs": {"A": 7}})
