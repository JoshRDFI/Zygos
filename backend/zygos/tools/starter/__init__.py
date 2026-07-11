"""Starter tool suite (M5 C3): concrete file/http/shell tools built on the C1/C2 contract.

Pure library — a caller (M8 turn loop) constructs and registers these with a ToolService.
Stability: Experimental.
"""

from zygos.tools.starter.fs import ReadFileTool, WriteFileTool
from zygos.tools.starter.http import HttpFetchTool
from zygos.tools.starter.shell import RunCommandTool

__all__ = ["ReadFileTool", "WriteFileTool", "HttpFetchTool", "RunCommandTool"]
