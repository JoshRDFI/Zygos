import pytest
from pydantic import BaseModel, ConfigDict, Field

from zygos.agent.schema import tool_schema
from zygos.tools.types import BaseTool, ToolMeta


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")
    city: str = Field(description="City name")


class PersonInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(description="Full name")
    home: Address = Field(description="Home address")


class _PersonTool(BaseTool):
    def __init__(self) -> None:
        self.meta = ToolMeta(name="person", description="Register a person.", input_model=PersonInput)

    async def execute(self, input, ctx):
        return {}


def test_schema_carries_meta_name_and_description():
    s = tool_schema(_PersonTool())
    assert s.name == "person"
    assert s.description == "Register a person."


def test_nested_model_is_inlined_no_refs_or_defs():
    s = tool_schema(_PersonTool())
    params = s.parameters
    # No $defs at the top and no $ref anywhere in the flattened schema.
    assert "$defs" not in params
    assert "$ref" not in _flatten_str(params)
    # The nested Address is inlined in place with its field descriptions preserved.
    home = params["properties"]["home"]
    assert home["properties"]["city"]["description"] == "City name"


def test_flat_field_descriptions_preserved():
    s = tool_schema(_PersonTool())
    assert s.parameters["properties"]["name"]["description"] == "Full name"


def test_cyclic_model_raises():
    class Node(BaseModel):
        model_config = ConfigDict(extra="forbid")
        child: "Node | None" = None
    Node.model_rebuild()

    class _CyclicTool(BaseTool):
        def __init__(self) -> None:
            self.meta = ToolMeta(name="cyc", description="x", input_model=Node)
        async def execute(self, input, ctx):
            return {}

    with pytest.raises(ValueError, match="cyclic"):
        tool_schema(_CyclicTool())


def _flatten_str(node) -> str:
    import json
    return json.dumps(node)
