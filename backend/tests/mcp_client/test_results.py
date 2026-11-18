"""Mapping MCP tool results to what a Zygos tool returns."""

from __future__ import annotations

import subprocess
import sys

import pytest

from zygos.mcp.results import McpToolError, map_result

types = pytest.importorskip("mcp_types")


def _result(*content, structured=None, is_error=False):
    return types.CallToolResult(content=list(content), structured_content=structured, is_error=is_error)


def _text(t):
    return types.TextContent(type="text", text=t)


def test_text_joined():
    assert map_result(_result(_text("one"), _text("two"))) == "one\ntwo"
    assert map_result(_result()) == ""


def test_structured_content():
    out = map_result(_result(_text("42 rows"), structured={"rows": 42}))
    assert out == {"text": "42 rows", "structured": {"rows": 42}}


def test_image_becomes_line():
    image = types.ImageContent(type="image", data="AAAA", mime_type="image/png")
    audio = types.AudioContent(type="audio", data="AAAA", mime_type="audio/wav")
    assert map_result(_result(_text("look:"), image, audio)) == (
        "look:\n[image returned — shown once artifacts arrive]\n[audio returned — shown once artifacts arrive]"
    )


def test_resources():
    link = types.ResourceLink(type="resource_link", uri="file:///a.txt", name="a")
    text = types.EmbeddedResource(
        type="resource", resource=types.TextResourceContents(uri="file:///b.txt", text="bee")
    )
    blob = types.EmbeddedResource(
        type="resource", resource=types.BlobResourceContents(uri="file:///c.bin", blob="AAAA")
    )
    assert map_result(_result(link, text, blob)) == "[resource: file:///a.txt]\nbee\n[resource: file:///c.bin]"


def test_is_error_raises():
    with pytest.raises(McpToolError) as info:
        map_result(_result(_text("bad input"), is_error=True))
    assert str(info.value) == "bad input"
    with pytest.raises(McpToolError) as info:
        map_result(_result(is_error=True))
    assert str(info.value)


def test_results_module_does_not_import_sdk():
    code = "import sys, zygos.mcp.results, zygos.mcp.remote; assert not {'mcp', 'mcp_types'} & set(sys.modules), 'SDK imported'"
    subprocess.run([sys.executable, "-c", code], check=True)
