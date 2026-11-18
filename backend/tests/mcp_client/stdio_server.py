"""A tiny MCP stdio server for the local-server tests; run as a script with the venv's python.

Tools: ``echo(text)``, ``crash()`` (exits 3 at once), ``pid()``, ``env(name)``,
``spam(n)`` (writes ``line 1`` .. ``line n`` to stderr, then ``done``) and ``grow()``
(adds a tool ``grown`` and announces the tool-list change).

At start it writes ``stdio test server starting`` to stderr. With ``CRASH_AT_START=1`` in
its environment it writes ``crashing at start`` to stderr and exits 3 before speaking MCP
(first writing ``leaky=<value>`` when ``LEAKY`` is set, to prove values are hidden).

``GRANDCHILD_PIDS=<file>``: at start, spawn a background child that ignores SIGTERM and
sleeps, appending its pid to <file> (proves the whole process group is stopped).
``HANG=1``: never answer (and don't exit when stdin closes).
``HANDSHAKE_ONLY=1``: refuse ``server/discover`` with Method-not-found, the way a
2025-era server does, so the client falls back to the initialize handshake; ``grow`` then
announces the change with the plain ``notifications/tools/list_changed``.
"""

import os
import subprocess
import sys
import time

STDERR_START = "stdio test server starting"
_GRANDCHILD = """
import os, signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1], "a") as f:
    f.write(f"{os.getpid()}\\n")
time.sleep(60)
"""


def main() -> None:
    sys.stderr.write(STDERR_START + "\n")
    sys.stderr.flush()
    if pid_file := os.environ.get("GRANDCHILD_PIDS"):
        before = _count(pid_file)
        subprocess.Popen(
            [sys.executable, "-c", _GRANDCHILD, pid_file],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        while _count(pid_file) == before:  # its pid is written before we go on
            time.sleep(0.01)
    if os.environ.get("HANG") == "1":
        time.sleep(60)  # never speaks MCP and ignores stdin closing
    if os.environ.get("CRASH_AT_START") == "1":
        if "LEAKY" in os.environ:
            sys.stderr.write(f"leaky={os.environ['LEAKY']}\n")
        sys.stderr.write("crashing at start\n")
        sys.stderr.flush()
        os._exit(3)

    from mcp.server.mcpserver import Context, MCPServer

    server = MCPServer("stdio-test", log_level="WARNING")

    @server.tool(structured_output=False)
    def echo(text: str) -> str:
        """Echo the text back."""
        return text

    @server.tool(structured_output=False)
    def crash() -> str:
        """Exit with code 3 at once."""
        sys.stderr.write("crash requested\n")
        sys.stderr.flush()
        os._exit(3)

    @server.tool(structured_output=False)
    def pid() -> int:
        """This process's id."""
        return os.getpid()

    @server.tool(structured_output=False)
    def env(name: str) -> str:
        """The value of an environment variable ("" when unset)."""
        return os.environ.get(name, "")

    @server.tool(structured_output=False)
    def spam(n: int) -> str:
        """Write n numbered lines to stderr, then a final ``done`` line."""
        for i in range(1, n + 1):
            sys.stderr.write(f"line {i}\n")
        sys.stderr.write("done\n")
        sys.stderr.flush()
        return "ok"

    @server.tool(structured_output=False)
    async def grow(ctx: Context) -> str:
        """Add a tool named ``grown`` and announce the change."""

        def grown() -> str:
            """A tool that appeared later."""
            return "grown"

        server.add_tool(grown)
        if os.environ.get("HANDSHAKE_ONLY") == "1":
            await ctx.session.send_tool_list_changed()
        else:
            await ctx.notify_tools_changed()
        return "grew"

    if os.environ.get("HANDSHAKE_ONLY") == "1":
        import anyio

        anyio.run(_serve_handshake_only, server)
    else:
        server.run("stdio")


def _count(pid_file: str) -> int:
    try:
        with open(pid_file) as f:
            return len(f.read().split())
    except FileNotFoundError:
        return 0


async def _serve_handshake_only(server) -> None:
    import anyio
    import mcp_types
    from mcp.server.lowlevel.server import NotificationOptions
    from mcp.server.stdio import stdio_server
    from mcp.shared.message import SessionMessage

    low = server._lowlevel_server
    async with stdio_server() as (read, write):
        send, receive = anyio.create_memory_object_stream(0)

        async def refuse_discover() -> None:
            async with send:
                async for item in read:
                    message = getattr(item, "message", None)
                    if getattr(message, "method", None) == "server/discover":
                        error = mcp_types.ErrorData(code=mcp_types.METHOD_NOT_FOUND, message="Method not found")
                        await write.send(SessionMessage(mcp_types.JSONRPCError(jsonrpc="2.0", id=message.id, error=error)))
                        continue
                    await send.send(item)

        async with anyio.create_task_group() as tg:
            tg.start_soon(refuse_discover)
            options = low.create_initialization_options(NotificationOptions(tools_changed=True))
            await low.run(receive, write, options)


if __name__ == "__main__":
    main()
