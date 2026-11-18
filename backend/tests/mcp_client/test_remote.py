"""Remote MCP client: one short connection per list/call, eras, headers, schema checks."""

from __future__ import annotations

import time

import pytest

pytest.importorskip("mcp")

from tests.mcp_client.servers import (  # noqa: E402
    BEARER_TOKEN,
    build_server,
    closed_port,
    echo_header_error,
    handshake_only,
    http_app,
    non_object_root,
    record_requests,
    require_bearer,
    serve,
    silent_port,
    sse_app,
)
from zygos.mcp.remote import (  # noqa: E402
    ListResult,
    McpToolError,
    McpUnavailable,
    call_remote,
    list_remote,
)
from zygos.mcp.types import ServerSpec  # noqa: E402

AUTH = "Authorization"


def _spec(url: str, *, transport: str = "http", timeout_s: float = 20.0, headers=()) -> ServerSpec:
    return ServerSpec(
        name="echo", transport=transport, url=url, header_names=list(headers), timeout_s=timeout_s
    )


@pytest.fixture
def modern_url():
    with serve(http_app(build_server())) as url:
        yield url


@pytest.fixture
def handshake_url():
    with serve(handshake_only(http_app(build_server()))) as url:
        yield url


@pytest.fixture
def bearer_url():
    with serve(require_bearer(http_app(build_server()))) as url:
        yield url


def _names(result: ListResult) -> set[str]:
    return {t.name for t in result.tools}


async def test_lists_modern_server_and_records_era(modern_url):
    result = await list_remote(_spec(modern_url), {}, era=None, discover=None)
    assert result.era == "2026-07-28"
    assert isinstance(result.discover, dict)
    assert "2026-07-28" in result.discover["supportedVersions"]
    assert {"echo", "pic"} <= _names(result)
    echo = next(t for t in result.tools if t.name == "echo")
    assert echo.input_schema["type"] == "object"
    assert echo.description == "Echo the text back."
    assert echo.problem is None
    # The SDK server's listing carries ttlMs 0 (no caching hint) -> no ttl.
    assert result.ttl_s is None


async def test_lists_handshake_server_era(handshake_url):
    result = await list_remote(_spec(handshake_url), {}, era=None, discover=None)
    assert result.era == "2025-11-25"
    assert result.discover is None
    assert {"echo", "pic"} <= _names(result)


async def test_handshake_only_server_really_rejects_discover(handshake_url):
    from mcp import Client

    with pytest.raises(Exception):
        async with Client(handshake_url, mode="2026-07-28") as client:
            await client.list_tools()


async def test_second_list_reuses_known_era(modern_url):
    first = await list_remote(_spec(modern_url), {}, era=None, discover=None)
    again = await list_remote(_spec(modern_url), {}, era=first.era, discover=first.discover)
    assert again.era == "2026-07-28"
    assert again.discover == first.discover
    assert _names(again) == _names(first)
    # A known handshake era (or garbage discover) still works through auto mode.
    third = await list_remote(_spec(modern_url), {}, era="2025-11-25", discover=None)
    assert third.era == "2026-07-28"
    fourth = await list_remote(_spec(modern_url), {}, era="2026-07-28", discover={"nonsense": 1})
    assert _names(fourth) == _names(first)


async def test_header_sent_and_required(bearer_url):
    spec = _spec(bearer_url, headers=[AUTH])
    result = await list_remote(spec, {AUTH: f"Bearer {BEARER_TOKEN}"}, era=None, discover=None)
    assert {"echo", "pic"} <= _names(result)
    with pytest.raises(McpUnavailable) as info:
        await list_remote(spec, {}, era=None, discover=None)
    assert "401" in str(info.value)


async def test_header_value_never_in_error(bearer_url):
    spec = _spec(bearer_url, headers=[AUTH])
    with pytest.raises(McpUnavailable) as info:
        await list_remote(spec, {AUTH: "Bearer s3cret"}, era=None, discover=None)
    assert "s3cret" not in str(info.value)
    assert "s3cret" not in repr(info.value)
    with pytest.raises(McpUnavailable) as info:
        await call_remote(spec, {AUTH: "Bearer s3cret"}, "echo", {"text": "x"}, era=None, discover=None)
    assert "s3cret" not in str(info.value)


async def test_unreachable_is_mcp_unavailable_within_timeout():
    spec = _spec(f"http://127.0.0.1:{closed_port()}/mcp", timeout_s=2)
    started = time.monotonic()
    with pytest.raises(McpUnavailable) as info:
        await list_remote(spec, {}, era=None, discover=None)
    assert time.monotonic() - started < 5
    assert str(info.value)
    started = time.monotonic()
    with pytest.raises(McpUnavailable):
        await call_remote(spec, {}, "echo", {"text": "x"}, era="2026-07-28", discover=None)
    assert time.monotonic() - started < 5


async def test_silent_server_times_out_as_unavailable():
    with silent_port() as port:
        spec = _spec(f"http://127.0.0.1:{port}/mcp", timeout_s=1)
        for era in (None, "2026-07-28"):
            started = time.monotonic()
            with pytest.raises(McpUnavailable) as info:
                await list_remote(spec, {}, era=era, discover=None)
            assert time.monotonic() - started < 3
            assert "within 1 s" in str(info.value)
        with pytest.raises(McpUnavailable):
            await call_remote(spec, {}, "echo", {"text": "x"}, era=None, discover=None)


async def test_bad_schema_tool_marked_problem_others_fine():
    server = build_server(bad_ref_tool=True)
    with serve(http_app(server)) as url:
        result = await list_remote(_spec(url), {}, era=None, discover=None)
        by_name = {t.name: t for t in result.tools}
        assert by_name["bad_ref"].problem
        assert by_name["echo"].problem is None
        assert by_name["pic"].problem is None
        assert await call_remote(_spec(url), {}, "echo", {"text": "still fine"}, era=result.era, discover=result.discover) == {
            "text": "still fine",
            "structured": {"result": "still fine"},
        }


@pytest.mark.parametrize("handshake", [False, True])
async def test_non_object_root_tool_marked_problem_others_fine(handshake):
    # The SDK validates tools/list replies per protocol version and would reject the whole
    # list over one tool's non-object root; that tool alone must be left out.
    app = non_object_root(http_app(build_server(string_root_tool=True), json_response=True))
    if handshake:
        app = handshake_only(app)
    with serve(app) as url:
        result = await list_remote(_spec(url), {}, era=None, discover=None)
    by_name = {t.name: t for t in result.tools}
    assert by_name["string_root"].input_schema == {"type": "string"}
    assert "object" in by_name["string_root"].problem
    assert by_name["echo"].problem is None


async def test_call_echo(modern_url, handshake_url):
    first = await list_remote(_spec(modern_url), {}, era=None, discover=None)
    out = await call_remote(_spec(modern_url), {}, "echo", {"text": "hi"}, era=first.era, discover=first.discover)
    assert out == {"text": "hi", "structured": {"result": "hi"}}
    out = await call_remote(_spec(handshake_url), {}, "echo", {"text": "yo"}, era="2025-11-25", discover=None)
    assert out == {"text": "yo", "structured": {"result": "yo"}}
    assert await call_remote(_spec(modern_url), {}, "pic", {}, era=None, discover=None) == (
        "[image returned — shown once artifacts arrive]"
    )


async def test_call_tool_failure_is_tool_error(modern_url):
    with pytest.raises(McpToolError):
        await call_remote(_spec(modern_url), {}, "echo", {}, era=None, discover=None)
    with pytest.raises(McpToolError):
        await call_remote(_spec(modern_url), {}, "no_such_tool", {}, era=None, discover=None)


async def test_sse_transport_lists_and_calls():
    with serve(require_bearer(sse_app(build_server())), path="/sse") as url:
        spec = _spec(url, transport="sse", headers=[AUTH])
        with pytest.raises(McpUnavailable) as info:
            await list_remote(spec, {AUTH: "Bearer s3cret"}, era=None, discover=None)
        assert "401" in str(info.value) and "s3cret" not in str(info.value)
        headers = {AUTH: f"Bearer {BEARER_TOKEN}"}
        result = await list_remote(spec, headers, era=None, discover=None)
        assert {"echo", "pic"} <= _names(result)
        assert result.era
        out = await call_remote(spec, headers, "echo", {"text": "old"}, era=result.era, discover=result.discover)
        assert out == {"text": "old", "structured": {"result": "old"}}


async def test_stdio_spec_rejected():
    spec = ServerSpec(name="fs", transport="stdio", command="x")
    with pytest.raises(McpUnavailable):
        await list_remote(spec, {}, era=None, discover=None)


async def test_nothing_declared_to_server():
    sent: list = []
    with serve(handshake_only(record_requests(http_app(build_server()), sent))) as url:
        await list_remote(_spec(url), {}, era=None, discover=None)
    init = next(m for m in sent if m.get("method") == "initialize")
    capabilities = init["params"]["capabilities"]
    assert not {"roots", "sampling", "elicitation", "tasks"} & {k for k, v in capabilities.items() if v}
    assert not any(m.get("method") == "logging/setLevel" for m in sent)


async def test_pinned_modern_era_recovers_after_downgrade(handshake_url):
    spec = _spec(handshake_url)
    result = await list_remote(spec, {}, era="2026-07-28", discover=None)
    assert result.era == "2025-11-25"
    assert {"echo", "pic"} <= _names(result)
    learned: list = []
    out = await call_remote(
        spec, {}, "echo", {"text": "hi"}, era="2026-07-28", discover=None,
        on_era=lambda era, discover: learned.append((era, discover)),
    )
    assert out == {"text": "hi", "structured": {"result": "hi"}}
    assert learned == [("2025-11-25", None)]


async def test_on_era_quiet_when_era_unchanged(modern_url):
    first = await list_remote(_spec(modern_url), {}, era=None, discover=None)
    learned: list = []
    await call_remote(
        _spec(modern_url), {}, "echo", {"text": "a"}, era=first.era, discover=first.discover,
        on_era=lambda era, discover: learned.append(era),
    )
    assert learned == []


async def test_handshake_era_call_skips_discover():
    sent: list = []
    with serve(record_requests(handshake_only(http_app(build_server())), sent)) as url:
        out = await call_remote(_spec(url), {}, "echo", {"text": "a"}, era="2025-11-25", discover=None)
        assert out["text"] == "a"
        assert not any(m.get("method") == "server/discover" for m in sent)
        assert any(m.get("method") == "initialize" for m in sent)
        sent.clear()
        # Listing still probes, so an upgraded server would be noticed.
        await list_remote(_spec(url), {}, era="2025-11-25", discover=None)
        assert any(m.get("method") == "server/discover" for m in sent)


async def test_short_header_value_scrubbed():
    with serve(echo_header_error("X-Key")) as url:
        spec = _spec(url, headers=["X-Key"], timeout_s=5)
        with pytest.raises(McpUnavailable) as info:
            await list_remote(spec, {"X-Key": "t0k"}, era=None, discover=None)
    assert "bad key" in str(info.value)
    assert "t0k" not in str(info.value)
