from pathlib import Path

from zygos.tools.build import ToolBuildContext
from zygos.tools.starter.fs import ReadFileTool, WriteFileTool
from zygos.tools.starter.http import HttpFetchTool
from zygos.tools.starter.shell import RunCommandTool
from zygos.tools.types import BaseTool


def _ctx(tmp_path, **settings):
    return ToolBuildContext(workspace=Path(tmp_path), settings=settings)


def test_read_file_from_config_uses_workspace_and_settings(tmp_path):
    tool = ReadFileTool.from_config(_ctx(tmp_path, max_bytes=10))
    assert isinstance(tool, ReadFileTool)
    assert tool._root == Path(tmp_path)
    assert tool._max_bytes == 10
    assert tool.meta.name == "read_file"


def test_write_file_from_config_defaults(tmp_path):
    tool = WriteFileTool.from_config(_ctx(tmp_path))
    assert tool._root == Path(tmp_path)
    assert tool._max_bytes == 1_048_576


def test_http_fetch_from_config_reads_settings(tmp_path):
    tool = HttpFetchTool.from_config(_ctx(tmp_path, timeout_s=5.0, ssrf_guard=False))
    assert tool.meta.name == "http_fetch"
    assert tool.meta.timeout_s == 5.0
    assert tool._ssrf_guard is False


def test_run_command_from_config_uses_workspace(tmp_path):
    tool = RunCommandTool.from_config(_ctx(tmp_path, timeout_s=7.0))
    assert tool._root == Path(tmp_path)
    assert tool.meta.timeout_s == 7.0


def test_base_tool_from_config_not_implemented_by_default():
    class Bare(BaseTool):
        pass
    import pytest
    with pytest.raises(NotImplementedError):
        Bare.from_config(ToolBuildContext(workspace=Path("."), settings={}))
