"""M5 C3 Task 3 — http_fetch: returned-as-output statuses, SSRF, transport retry."""

import httpx
import pytest

from zygos.errors import ToolError, ToolTransient
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.tools.executor import execute_tool
from zygos.tools.starter.http import HttpFetchTool, _validate_url
from zygos.tools.types import ToolCall


def _ctx():
    return root_context(InProcessEventBus())


def _tool(handler, **kw):
    return HttpFetchTool(transport=httpx.MockTransport(handler), ssrf_guard=False, **kw)


@pytest.mark.asyncio
async def test_fetch_200():
    tool = _tool(lambda req: httpx.Response(200, text="hello"))
    res = await execute_tool(tool, ToolCall(tool="http_fetch", args={"url": "http://x/"}), _ctx())
    assert res.ok is True
    assert res.output["status"] == 200
    assert res.output["body"] == "hello"
    assert res.output["truncated"] is False


@pytest.mark.asyncio
async def test_fetch_404_is_output_not_error():
    tool = _tool(lambda req: httpx.Response(404, text="nope"))
    res = await execute_tool(tool, ToolCall(tool="http_fetch", args={"url": "http://x/"}), _ctx())
    assert res.ok is True
    assert res.output["status"] == 404


@pytest.mark.asyncio
async def test_fetch_500_is_output_not_retried():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500, text="boom")

    tool = _tool(handler)
    res = await execute_tool(tool, ToolCall(tool="http_fetch", args={"url": "http://x/"}), _ctx())
    assert res.ok is True
    assert res.output["status"] == 500
    assert len(calls) == 1   # 5xx is a real answer — not retried


@pytest.mark.asyncio
async def test_fetch_body_truncation():
    tool = _tool(lambda req: httpx.Response(200, text="hello world"), max_bytes=5)
    res = await execute_tool(tool, ToolCall(tool="http_fetch", args={"url": "http://x/"}), _ctx())
    assert res.output["body"] == "hello"
    assert res.output["truncated"] is True


@pytest.mark.asyncio
async def test_transport_fault_retries_then_fails():
    calls = []
    sleeps = []

    def handler(req):
        calls.append(1)
        raise httpx.ConnectError("refused")

    tool = _tool(handler)

    async def fake_sleep(d):
        sleeps.append(d)

    res = await execute_tool(
        tool, ToolCall(tool="http_fetch", args={"url": "http://x/"}), _ctx(), sleep=fake_sleep
    )
    assert res.ok is False
    assert res.error_code == "tool_transient"
    assert len(calls) == 3          # RetryPolicy(attempts=3)
    assert len(sleeps) == 2         # two backoffs between three attempts


@pytest.mark.asyncio
async def test_redirect_revalidated_and_blocked():
    def handler(req):
        return httpx.Response(302, headers={"location": "http://127.0.0.1/"})

    # ssrf_guard ON; first hop is a public IP literal (offline-safe), redirect target is loopback.
    tool = HttpFetchTool(transport=httpx.MockTransport(handler), ssrf_guard=True)
    res = await execute_tool(
        tool, ToolCall(tool="http_fetch", args={"url": "http://93.184.216.34/"}), _ctx()
    )
    assert res.ok is False
    assert res.error_code == "tool_error"
    assert "ssrf" in res.error_message.lower()


def test_validate_url_blocks_private_and_metadata():
    with pytest.raises(ToolError):
        _validate_url("http://127.0.0.1/", ("http", "https"))
    with pytest.raises(ToolError):
        _validate_url("http://10.0.0.5/", ("http", "https"))
    with pytest.raises(ToolError):
        _validate_url("http://169.254.169.254/latest/meta-data/", ("http", "https"))


def test_validate_url_blocks_bad_scheme():
    with pytest.raises(ToolError):
        _validate_url("file:///etc/passwd", ("http", "https"))


def test_validate_url_allows_public_ip():
    _validate_url("http://93.184.216.34/", ("http", "https"))   # must not raise
