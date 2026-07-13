import pytest
from pydantic import ValidationError

from zygos.agent.config import ToolLoopConfig


def test_defaults():
    c = ToolLoopConfig()
    assert c.max_iterations == 8
    assert c.default_tool_choice == "auto"


def test_max_iterations_must_be_at_least_one():
    with pytest.raises(ValidationError):
        ToolLoopConfig(max_iterations=0)
