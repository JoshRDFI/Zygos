"""Starter tool suite (M5): concrete file/http/shell tools built on the tool contract.

Pure library — a caller (M8 turn loop) constructs and registers these with a ToolService.
Stability: Experimental.
"""

from zygos.tools.starter.fs import ReadFileTool, WriteFileTool
from zygos.tools.starter.http import HttpFetchTool
from zygos.tools.starter.shell import RunCommandTool

__all__ = ["ReadFileTool", "WriteFileTool", "HttpFetchTool", "RunCommandTool"]
