"""Reusable MCP test servers, served over real HTTP on 127.0.0.1.

Each server is the SDK's ``MCPServer`` run by uvicorn in a background thread on a
socket bound to a free port. Small ASGI wrappers give the variants:

* ``require_bearer`` — 401 unless ``Authorization: Bearer <token>`` (the Mnemosyne stand-in).
* ``handshake_only`` — answers ``server/discover`` (and any request announcing a
  modern protocol version) with JSON-RPC ``Method not found``, the way a 2025-era
  server does, so ``mode="auto"`` falls back to the initialize handshake. The SDK's
  server always speaks both eras and has no switch to turn the modern one off, so
  the refusal is done at the HTTP layer, in front of the real app.
* ``non_object_root`` — rewrites a ``tools/list`` reply so a marked tool's input
  schema becomes ``{"type": "string"}``. The SDK server refuses to send such a
  schema itself (it validates its own replies), so it is rewritten on the wire;
  needs the app built with ``json_response=True``.

Use ``serve(app)`` as a context manager; it yields the base URL and on exit stops
uvicorn and joins the thread (bounded), so nothing outlives the test.
"""

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

BEARER_TOKEN = "t0k"
STRING_ROOT_MARK = "x-zygos-test-string-root"
BAD_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"a": {"$ref": "#/$defs/Missing"}},
}
TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
    b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def build_server(*, name: str = "echo", bad_ref_tool: bool = False, string_root_tool: bool = False):
    """An MCPServer with ``echo(text)`` and ``pic()``, plus optional broken-schema tools."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.utilities.types import Image

    server = MCPServer(name, log_level="WARNING")

    @server.tool()
    def echo(text: str) -> str:
        """Echo the text back."""
        return text

    @server.tool()
    def pic() -> Image:
        """Return a tiny image."""
        return Image(data=TINY_PNG, format="png")

    if bad_ref_tool:

        @server.tool()
        def bad_ref(a: str) -> str:
            """A tool whose schema points at a definition that doesn't exist."""
            return a

        server._tool_manager.get_tool("bad_ref").parameters = dict(BAD_REF_SCHEMA)

    if string_root_tool:

        @server.tool()
        def string_root(a: str) -> str:
            """A tool whose schema root becomes a string schema on the wire."""
            return a

        tool = server._tool_manager.get_tool("string_root")
        tool.parameters = {**tool.parameters, STRING_ROOT_MARK: True}

    return server


def http_app(server, *, json_response: bool = False):
    return server.streamable_http_app(json_response=json_response)


def sse_app(server):
    return server.sse_app()


# ---- ASGI wrappers -----------------------------------------------------------


async def _read_body(receive) -> bytes:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body"):
            return body


def _replay(body: bytes, receive):
    sent = False

    async def replay():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        # The body is consumed; from here on the real channel reports the disconnect.
        return await receive()

    return replay


async def _send_json(send, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
        }
    )
    await send({"type": "http.response.body", "body": body})


def require_bearer(app, token: str = BEARER_TOKEN):
    expected = f"Bearer {token}".encode()

    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            got = dict(scope["headers"]).get(b"authorization")
            if got != expected:
                await _send_json(send, 401, {"error": "unauthorized"})
                return
        await app(scope, receive, send)

    return wrapped


def handshake_only(app):
    from mcp_types.version import HANDSHAKE_PROTOCOL_VERSIONS

    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await app(scope, receive, send)
            return
        body = await _read_body(receive)
        try:
            message = json.loads(body)
        except ValueError:
            message = None
        version = dict(scope["headers"]).get(b"mcp-protocol-version", b"").decode("latin-1")
        modern_header = bool(version) and version not in HANDSHAKE_PROTOCOL_VERSIONS
        if isinstance(message, dict) and (message.get("method") == "server/discover" or modern_header):
            await _send_json(
                send,
                400,
                {
                    "jsonrpc": "2.0",
                    "id": message.get("id"),
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )
            return
        await app(scope, _replay(body, receive), send)

    return wrapped


def record_requests(app, sink: list):
    """Append every JSON-RPC message POSTed to ``app`` to ``sink`` (for asserting what was sent)."""

    async def wrapped(scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            await app(scope, receive, send)
            return
        body = await _read_body(receive)
        try:
            sink.append(json.loads(body))
        except ValueError:
            pass
        await app(scope, _replay(body, receive), send)

    return wrapped


def echo_header_error(header: str):
    """An app that answers every POST with a JSON-RPC error quoting ``header``'s value."""

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return
        await _read_body(receive)
        value = dict(scope["headers"]).get(header.lower().encode(), b"").decode("latin-1")
        await _send_json(
            send, 400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": f"bad key {value}"}}
        )

    return app


def non_object_root(app):
    """Rewrite tools/list replies: a tool carrying STRING_ROOT_MARK gets ``{"type": "string"}``."""

    async def wrapped(scope, receive, send):
        if scope["type"] != "http":
            await app(scope, receive, send)
            return
        start: dict[str, Any] = {}
        chunks: list[bytes] = []

        async def capture(message):
            if message["type"] == "http.response.start":
                start.update(message)
                return
            if message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if message.get("more_body"):
                    return
                body = _rewrite(b"".join(chunks))
                headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
                headers.append((b"content-length", str(len(body)).encode()))
                await send({**start, "headers": headers})
                await send({"type": "http.response.body", "body": body})
                return
            await send(message)

        await app(scope, receive, capture)

    return wrapped


def _rewrite(body: bytes) -> bytes:
    try:
        message = json.loads(body)
    except ValueError:
        return body
    tools = message.get("result", {}).get("tools") if isinstance(message, dict) else None
    if not isinstance(tools, list):
        return body
    for tool in tools:
        if isinstance(tool.get("inputSchema"), dict) and STRING_ROOT_MARK in tool["inputSchema"]:
            tool["inputSchema"] = {"type": "string"}
    return json.dumps(message).encode()


# ---- serving -----------------------------------------------------------------


def closed_port() -> int:
    """A localhost port nothing listens on (bound then released)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def silent_port() -> Iterator[int]:
    """A localhost port that accepts TCP connections (backlog) but never answers."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        yield sock.getsockname()[1]


@contextmanager
def serve(app, *, path: str = "/mcp") -> Iterator[str]:
    """Run ``app`` with uvicorn on a free 127.0.0.1 port; yield ``http://127.0.0.1:<port><path>``."""
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(
        app, log_level="warning", access_log=False, lifespan="on", timeout_graceful_shutdown=3
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("test MCP server did not start")
            time.sleep(0.01)
        yield f"http://127.0.0.1:{port}{path}"
    finally:
        server.should_exit = True
        thread.join(10)
        sock.close()
        if thread.is_alive():  # pragma: no cover - a hang here is a test bug worth seeing
            raise RuntimeError("test MCP server did not stop")
