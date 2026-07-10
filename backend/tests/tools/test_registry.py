"""M5 C1 Task 3 — ToolRegistry."""

import pytest
from pydantic import BaseModel

from zygos.errors import ToolError
from zygos.tools.registry import ToolRegistry
from zygos.tools.types import BaseTool, ToolContext, ToolMeta


class _In(BaseModel):
    x: int


def _tool(name: str) -> BaseTool:
    class _T(BaseTool):
        meta = ToolMeta(name=name, description="d", input_model=_In)

        async def execute(self, input: _In, ctx: ToolContext):
            return input.x

    return _T()


def test_register_and_get():
    reg = ToolRegistry()
    t = _tool("alpha")
    reg.register(t)
    assert reg.get("alpha") is t


def test_get_unknown_returns_none():
    assert ToolRegistry().get("nope") is None


def test_duplicate_name_raises():
    reg = ToolRegistry()
    reg.register(_tool("dup"))
    with pytest.raises(ToolError):
        reg.register(_tool("dup"))


def test_list_returns_metas_in_insertion_order():
    reg = ToolRegistry()
    reg.register(_tool("first"))
    reg.register(_tool("second"))
    names = [m.name for m in reg.list()]
    assert names == ["first", "second"]
    assert all(isinstance(m, ToolMeta) for m in reg.list())
