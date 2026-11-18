"""A tiny MCP stdio server for the local-server tests; run as a script with the venv's python.

Tools: ``echo(text)``, ``crash()`` (exits 3 at once), ``pid()``, ``env(name)``,
``spam(n)`` (writes ``line 1`` .. ``line n`` to stderr, then ``done``) and ``grow()``
(adds a tool ``grown`` and announces the tool-list change).

At start it writes ``stdio test server starting`` to stderr. With ``CRASH_AT_START=1`` in
its environment it writes ``crashing at start`` to stderr and exits 3 before speaking MCP
(first writing ``leaky=<value>`` when ``LEAKY`` is set, to prove values are hidden).
"""

import os
import sys

STDERR_START = "stdio test server starting"


def main() -> None:
    sys.stderr.write(STDERR_START + "\n")
    sys.stderr.flush()
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
        await ctx.notify_tools_changed()
        return "grew"

    server.run("stdio")


if __name__ == "__main__":
    main()
