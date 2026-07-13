import json
from pathlib import Path

from zygos.agent.schema import tool_schema
from zygos.tools.starter.fs import ReadFileTool, WriteFileTool
from zygos.tools.starter.http import HttpFetchTool
from zygos.tools.starter.shell import RunCommandTool


def _starter_tools(tmp_path: Path):
    return [ReadFileTool(tmp_path), WriteFileTool(tmp_path), HttpFetchTool(), RunCommandTool(tmp_path)]


def test_every_input_field_has_a_description(tmp_path):
    for tool in _starter_tools(tmp_path):
        schema = tool_schema(tool)
        props = schema.parameters.get("properties", {})
        assert props, f"{tool.meta.name} has no input properties"
        for field, spec in props.items():
            assert spec.get("description"), f"{tool.meta.name}.{field} lacks a description"


def test_schemas_are_flat_no_refs(tmp_path):
    for tool in _starter_tools(tmp_path):
        blob = json.dumps(tool_schema(tool).parameters)
        assert "$ref" not in blob and "$defs" not in blob


def test_descriptions_are_selection_oriented(tmp_path):
    # Selection-oriented = says when to use it, not just what it is. Heuristic floor:
    # a description of reasonable length (the conventions ask for "what + when").
    for tool in _starter_tools(tmp_path):
        assert len(tool.meta.description) >= 40, f"{tool.meta.name} description too terse"
