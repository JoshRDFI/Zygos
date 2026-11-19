import json

import pytest

from zygos.mcp.config import (
    McpConfigError,
    check_server_names,
    describe,
    parse_servers,
    zygos_tool_name,
)

DESKTOP = {
    "mcpServers": {
        "files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me"]},
        "search": {"command": "uvx", "args": ["search-mcp"], "env": {"SEARCH_API_KEY": "sk-123"}},
        "comfyui": {"url": "http://localhost:8188/mcp", "headers": {"Authorization": "Bearer sk-123"}},
    }
}


def test_parses_with_and_without_outer_key():
    inner = {"a": {"command": "x"}}
    assert [p.spec.name for p in parse_servers(json.dumps({"mcpServers": inner}))] == ["a"]
    assert [p.spec.name for p in parse_servers(json.dumps(inner))] == ["a"]


def test_claude_desktop_example():
    parsed = {p.spec.name: p for p in parse_servers(json.dumps(DESKTOP))}
    assert [parsed[n].spec.transport for n in ("files", "search", "comfyui")] == ["stdio", "stdio", "http"]
    assert parsed["search"].spec.env_names == ["SEARCH_API_KEY"]
    assert parsed["search"].secrets == {"mcp:search:env:SEARCH_API_KEY": "sk-123"}
    assert parsed["comfyui"].spec.header_names == ["Authorization"]
    assert parsed["comfyui"].secrets == {"mcp:comfyui:header:Authorization": "Bearer sk-123"}


def test_unknown_keys_kept():
    (p,) = parse_servers(json.dumps({"a": {"command": "x", "disabled": True, "type": "stdio"}}))
    assert p.spec.extra["disabled"] is True


def test_sse_labelled():
    (p,) = parse_servers(json.dumps({"a": {"url": "http://h/sse", "type": "sse"}}))
    assert p.spec.transport == "sse"
    assert describe(p.spec) == "This connects to http://h/sse (deprecated transport)"
    (q,) = parse_servers(json.dumps({"a": {"url": "http://h/m", "type": "streamable-http"}}))
    assert q.spec.transport == "http"
    assert describe(q.spec) == "This connects to http://h/m"


def test_missing_command_and_url_errors():
    with pytest.raises(McpConfigError, match="broken"):
        parse_servers(json.dumps({"broken": {"args": []}}))


def test_bad_input_errors():
    with pytest.raises(McpConfigError):
        parse_servers("not json")
    with pytest.raises(McpConfigError, match="a"):
        parse_servers(json.dumps({"a": {"command": "x", "env": {"K": 5}}}))
    with pytest.raises(McpConfigError, match="a:b"):
        parse_servers(json.dumps({"a:b": {"command": "x", "env": {"K": "v"}}}))
    with pytest.raises(McpConfigError, match="BAD NAME"):
        parse_servers(json.dumps({"a": {"command": "x", "env": {"BAD NAME": "v"}}}))


def test_secret_values_never_in_repr():
    (p,) = parse_servers(json.dumps({"a": {"command": "x", "env": {"K": "sk-123"}}}))
    assert "sk-123" not in repr(p)
    assert "sk-123" not in repr(p.spec)
    assert "sk-123" not in str(p)


def test_tool_name_cleaning():
    assert zygos_tool_name("my server", "read.file") == "my_server__read_file"


def test_long_name_hashed_stable():
    a = zygos_tool_name("s", "t" * 100)
    assert len(a) == 64
    assert a == zygos_tool_name("s", "t" * 100)
    assert a != zygos_tool_name("s", "t" * 99 + "u")
    assert a != zygos_tool_name("s", "t" * 101)


def test_cleaned_collision_reported():
    assert len(check_server_names(["a.b", "a_b"], [])) == 1
    assert len(check_server_names(["a.b"], ["a_b"])) == 1
    assert check_server_names(["a_b"], ["a_b"]) == []


def test_describe_quotes_command():
    (p,) = parse_servers(json.dumps({"a": {"command": "node", "args": ["my file.js"]}}))
    assert describe(p.spec) == "This runs `node 'my file.js'` on this machine as you"


def test_parse_rejects_double_underscore_server_name():
    with pytest.raises(McpConfigError, match=r"a__b.*'__'"):
        parse_servers('{"a__b": {"command": "x"}}')
    with pytest.raises(McpConfigError, match="reserved"):
        parse_servers('{"a.b": {"command": "x"}, "c__d": {"command": "x"}}')
    with pytest.raises(McpConfigError, match="reserved"):
        parse_servers('{"a_.b": {"command": "x"}}')  # cleans to a__b


@pytest.mark.parametrize("raw", ['"abc"', "0", "-1", "true", "NaN", "1e309", "-Infinity", "601", "[5]", "null"])
def test_bad_timeout_rejected_naming_the_server(raw):
    text = '{"slowsrv": {"command": "x", "timeout_s": ' + raw + "}}"
    with pytest.raises(McpConfigError, match="slowsrv.*timeout_s"):
        parse_servers(text)


@pytest.mark.parametrize(("raw", "want"), [("30", 30.0), ("0.5", 0.5), ("600", 600.0)])
def test_good_timeout_kept(raw, want):
    [parsed] = parse_servers('{"a": {"url": "http://h/mcp", "timeout_s": ' + raw + "}}")
    assert parsed.spec.timeout_s == want
