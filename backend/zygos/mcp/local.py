"""Local MCP servers (stdio): one process per run, connected for as long as it runs.

Zygos owns the process (``anyio.open_process``) rather than using the SDK's
``stdio_client``, which hides the exit code and needs a real file for stderr. The SDK
``Client`` talks to the process through ``_pipes``, a ``Transport`` over its stdin/stdout
(newline-delimited JSON-RPC, as the SDK frames stdio); stderr is read into a bounded
``StderrTail``.

Lifecycle, per ``start()``: the first unexpected end (exit, or a connection that fails) is
restarted once; the second leaves the server **stopped** with its exit code and stderr
tail, and nothing restarts it until ``start()`` is called again. ``stop()`` closes stdin,
then terminates the process group and kills it after 5 s. Events go to
``on_event(kind, detail)``: ``started`` (connected; list its tools), ``restarted`` (it
ended and is being started again), ``stopped``, ``failed`` (could not be started or
talked to), ``tools_changed`` (the server announced a new tool list).

The process gets the SDK's safe default environment plus its own env (values from the
secret store); those values are hidden from every event, reason and the stderr tail.
Nothing is declared to the server: no roots, sampling, elicitation or logging.

The MCP SDK is imported inside the functions, so importing this module never imports it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Literal

from zygos.mcp.remote import (
    ListResult,
    _guard,
    _HttpStatus,
    _is_modern,
    _scrub,
    _translate,
    dump_discover,
    list_pages,
    ttl_seconds,
)
from zygos.mcp.results import McpToolError, McpUnavailable, map_result
from zygos.mcp.types import ServerSpec

__all__ = ["LocalServer", "StderrTail"]

logger = logging.getLogger("zygos.mcp")

Status = Literal["running", "stopped", "not_started"]

_STDIN_GRACE_S = 0.5  # after stdin closes, time for the server to exit on its own
_KILL_AFTER_S = 5.0  # after terminate, time before kill
_REAP_S = 2.0  # after kill, time for the event loop to see the death
_EXIT_GRACE_S = 0.5  # after a broken connection, time for a crashing process's exit to show
_STDERR_DRAIN_S = 1.0  # after the process is gone, time to read the rest of its stderr
_POLL_S = 0.02


class StderrTail:
    """The last 200 lines or 16 KB (UTF-8 bytes) of a stream, whichever is smaller."""

    MAX_LINES = 200
    MAX_BYTES = 16 * 1024

    def __init__(self) -> None:
        self._buf = b""

    def reset(self) -> None:
        self._buf = b""

    def feed(self, chunk: bytes) -> None:
        buf = self._buf + chunk
        if len(buf) > self.MAX_BYTES:
            buf = buf[-self.MAX_BYTES :]
            newline = buf.find(b"\n")
            if 0 <= newline < len(buf) - 1:
                buf = buf[newline + 1 :]  # keep whole lines only
            else:
                buf = buf.lstrip(bytes(range(0x80, 0xC0)))  # no torn UTF-8 sequence at the start
        ends_line = buf.endswith(b"\n")
        lines = buf.count(b"\n") + (0 if ends_line or not buf else 1)
        if lines > self.MAX_LINES:
            buf = b"\n".join(buf.split(b"\n")[-(self.MAX_LINES + ends_line) :])
        self._buf = buf

    @property
    def text(self) -> str:
        return self._buf.decode("utf-8", errors="replace")


@dataclass
class _End:
    """How one process run ended."""

    exited: bool = False  # the process exited on its own (vs. we stopped or killed it)
    spawn_failed: bool = False
    reason: str | None = None
    exit_code: int | None = None


class LocalServer:
    def __init__(
        self,
        spec: ServerSpec,
        env: dict[str, str],
        *,
        on_event: Callable[[str, str | None], None],
    ) -> None:
        self.spec = spec
        self._env = dict(env)
        self._on_event = on_event
        self._status: Status = "not_started"
        self._exit_code: int | None = None
        self._tail = StderrTail()
        self._client: Any = None
        self._era: str | None = None
        self._discover: dict[str, Any] | None = None
        self._runner: asyncio.Task[None] | None = None
        self._stop: asyncio.Event | None = None
        self._settled: asyncio.Event | None = None

    # ---- state ---------------------------------------------------------------

    @property
    def status(self) -> Status:
        """``running`` while connected; ``not_started`` before the first start and while
        (re)starting; ``stopped`` after stop() or the second unexpected end."""
        return self._status

    @property
    def exit_code(self) -> int | None:
        return self._exit_code

    @property
    def stderr_tail(self) -> str:
        return _scrub(self._tail.text, self._env)

    @property
    def era(self) -> str | None:
        return self._era

    # ---- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Start the server (no-op while already started); returns once it is running or
        has stopped. A stopped server starts again with a fresh restart allowance."""
        if self._runner is None or self._runner.done():
            self._stop = asyncio.Event()
            self._settled = asyncio.Event()
            self._exit_code = None
            self._status = "not_started"
            self._runner = asyncio.create_task(self._run(self._stop, self._settled), name=f"mcp-local:{self.spec.name}")
        assert self._settled is not None
        await self._settled.wait()

    async def stop(self) -> None:
        """Stop the server: close stdin, terminate, kill after 5 s. Idempotent."""
        runner, stop = self._runner, self._stop
        if runner is None or stop is None:
            return
        stop.set()
        await asyncio.shield(runner)

    # ---- use -----------------------------------------------------------------

    async def list_tools(self) -> ListResult:
        """List the running server's tools; each tool's schema is checked."""
        client = self._connected()
        era = self._era or ""
        try:
            import anyio

            with anyio.fail_after(self.spec.timeout_s):
                tools, ttl_ms = await list_pages(client)
        except TimeoutError:
            raise McpUnavailable(f"no answer within {self.spec.timeout_s:g} s") from None
        except (McpUnavailable, McpToolError):
            raise
        except Exception as exc:  # noqa: BLE001 - every failure becomes a readable reason
            raise _translate(exc, _HttpStatus(), self._env, during_call=False) from None
        return ListResult(era=era, discover=self._discover, tools=tools, ttl_s=ttl_seconds(era, ttl_ms))

    async def call(self, tool: str, args: dict[str, Any], timeout_s: float) -> Any:
        """Call one tool on the running server; returns ``map_result`` of the reply."""
        client = self._connected()
        try:
            import anyio

            with anyio.fail_after(timeout_s):
                result = await client.call_tool(tool, args, read_timeout_seconds=timeout_s)
        except TimeoutError:
            raise McpUnavailable(f"no answer within {timeout_s:g} s") from None
        except (McpUnavailable, McpToolError):
            raise
        except Exception as exc:  # noqa: BLE001 - every failure becomes a readable reason
            raise _translate(exc, _HttpStatus(), self._env, during_call=True) from None
        return map_result(result)

    def _connected(self) -> Any:
        client = self._client
        if client is None or self._status != "running":
            raise McpUnavailable(f"{self.spec.name} is not running")
        return client

    # ---- runner --------------------------------------------------------------

    def _emit(self, kind: str, detail: str | None) -> None:
        detail = None if detail is None else _scrub(detail, self._env)
        logger.info("mcp server %s: %s%s", self.spec.name, kind, f" ({detail})" if detail else "")
        try:
            self._on_event(kind, detail)
        except Exception:  # noqa: BLE001 - a listener's fault must not stop the server's lifecycle
            logger.exception("mcp server %s: event listener failed on %s", self.spec.name, kind)

    def _end_detail(self, end: _End) -> str:
        if end.exited:
            lines = [line for line in self._tail.text.splitlines() if line.strip()]
            return f"exit {end.exit_code}" + (f": {lines[-1]}" if lines else "")
        return end.reason or "the server could not be reached"

    async def _run(self, stop: asyncio.Event, settled: asyncio.Event) -> None:
        restarts_left = 1
        try:
            while True:
                end = await self._run_once(stop, settled)
                self._exit_code = end.exit_code if end.exited else None
                if stop.is_set():
                    self._status = "stopped"
                    self._emit("stopped", None)
                    return
                if end.spawn_failed:
                    self._status = "stopped"
                    self._emit("failed", self._end_detail(end))
                    return
                if restarts_left:
                    restarts_left -= 1
                    self._emit("restarted", self._end_detail(end))
                    continue
                self._status = "stopped"
                self._emit("stopped" if end.exited else "failed", self._end_detail(end))
                return
        except Exception:  # noqa: BLE001 - a bug here must still leave a clear state
            logger.exception("mcp server %s: runner failed", self.spec.name)
            self._status = "stopped"
            self._emit("failed", "internal error while running the server")
        finally:
            self._client = None
            if self._status != "stopped":
                self._status = "stopped"
            settled.set()

    async def _run_once(self, stop: asyncio.Event, settled: asyncio.Event) -> _End:
        import anyio
        from mcp.client.stdio import get_default_environment

        end = _End()
        self._tail.reset()
        command = self.spec.command
        if not command:
            end.spawn_failed, end.reason = True, "no command to run"
            return end
        try:
            process = await anyio.open_process(
                [command, *self.spec.args],
                cwd=self.spec.cwd,
                env=get_default_environment() | self._env,
                start_new_session=sys.platform != "win32",
            )
        except (OSError, ValueError) as exc:
            detail = getattr(exc, "strerror", None) or str(exc) or type(exc).__name__
            end.spawn_failed, end.reason = True, f"could not start {command}: {detail}"
            return end

        stderr_done = anyio.Event()
        async with anyio.create_task_group() as outer:
            outer.start_soon(self._read_stderr, process, stderr_done)
            try:
                async with anyio.create_task_group() as inner:
                    inner.start_soon(_wait_set, stop, inner.cancel_scope)
                    inner.start_soon(self._watch_exit, process, end, inner.cancel_scope)
                    inner.start_soon(self._session, process, end, settled, inner.cancel_scope)
            finally:
                self._client = None
                if self._status == "running":
                    self._status = "not_started"
                with anyio.CancelScope(shield=True):
                    await _shut_down(process)
                    with anyio.move_on_after(_STDERR_DRAIN_S):
                        await stderr_done.wait()
                    outer.cancel_scope.cancel()
        with anyio.CancelScope(shield=True):
            await _release(process)
        end.exit_code = process.returncode
        return end

    async def _read_stderr(self, process: Any, done: Any) -> None:
        import anyio

        try:
            async for chunk in process.stderr:
                self._tail.feed(chunk)
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            pass
        finally:
            done.set()

    async def _watch_exit(self, process: Any, end: _End, scope: Any) -> None:
        import anyio

        while process.returncode is None:
            await anyio.sleep(_POLL_S)
        end.exited = True
        scope.cancel()

    async def _session(self, process: Any, end: _End, settled: asyncio.Event, scope: Any) -> None:
        import anyio
        from mcp import Client

        timeout_s = self.spec.timeout_s
        try:
            with anyio.CancelScope(deadline=anyio.current_time() + timeout_s) as connecting:
                client = Client(
                    _pipes(process),
                    mode="auto",
                    read_timeout_seconds=timeout_s,
                    cache=None,
                    message_handler=self._on_message,
                )
                async with client:
                    self._era = client.protocol_version
                    self._discover = dump_discover(client)
                    async with anyio.create_task_group() as listeners:
                        tools = client.server_capabilities.tools
                        if _is_modern(self._era) and tools is not None and tools.list_changed:
                            # Subscribed before "started", so no change after a listing is missed.
                            await listeners.start(self._listen, client)
                        connecting.deadline = math.inf
                        self._client = client
                        self._status = "running"
                        self._emit("started", None)
                        settled.set()
                        await anyio.sleep_forever()
            if connecting.cancelled_caught:
                end.reason = f"no answer within {timeout_s:g} s"
        except Exception as exc:  # noqa: BLE001 - every failure becomes a readable reason
            end.reason = str(_translate(exc, _HttpStatus(), self._env, during_call=False))
            # A crashing process breaks the connection a moment before its exit shows.
            with anyio.move_on_after(_EXIT_GRACE_S):
                while process.returncode is None:
                    await anyio.sleep(_POLL_S)
            end.exited = process.returncode is not None
        finally:
            self._client = None
        scope.cancel()

    async def _listen(self, client: Any, *, task_status: Any) -> None:
        """Modern servers deliver tool-list changes on a ``subscriptions/listen`` stream.
        Reports ready once subscribed, or once subscribing failed (changes are then missed)."""
        try:
            async with client.listen(tools_list_changed=True) as subscription:
                task_status.started()
                async for _event in subscription:
                    self._emit("tools_changed", None)
        except Exception as exc:  # noqa: BLE001 - losing the stream only loses change hints
            logger.debug("mcp server %s: change stream ended: %s", self.spec.name, type(exc).__name__)
        finally:
            with contextlib.suppress(RuntimeError):  # already reported ready
                task_status.started()

    async def _on_message(self, message: Any) -> None:
        """Handshake-era servers send tool-list changes as plain notifications (modern ones
        come through ``_listen``; the SDK also passes them here, so they're not counted twice)."""
        if not _is_modern(self._era) and getattr(message, "method", None) == "notifications/tools/list_changed":
            self._emit("tools_changed", None)


# ---- process plumbing -----------------------------------------------------------


async def _wait_set(event: asyncio.Event, scope: Any) -> None:
    await event.wait()
    scope.cancel()


@asynccontextmanager
async def _pipes(process: Any) -> AsyncIterator[tuple[Any, Any]]:
    """The SDK ``Transport`` over a process's stdin/stdout: one JSON-RPC message per line."""
    import anyio
    import mcp_types
    from anyio.streams.text import TextReceiveStream
    from mcp.shared.message import SessionMessage

    read_writer, read_stream = anyio.create_memory_object_stream[SessionMessage | Exception](0)
    write_stream, write_reader = anyio.create_memory_object_stream[SessionMessage](0)

    def parse(line: str) -> SessionMessage | Exception:
        try:
            return SessionMessage(mcp_types.jsonrpc_message_adapter.validate_json(line, by_name=False))
        except ValueError as exc:
            return exc  # the session reports it; the connection goes on

    async def stdout_reader() -> None:
        try:
            async with read_writer:
                buffer = ""
                async for chunk in TextReceiveStream(process.stdout, encoding="utf-8", errors="replace"):
                    lines = (buffer + chunk).split("\n")
                    buffer = lines.pop()
                    for line in lines:
                        if line.strip():
                            await read_writer.send(parse(line))
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            pass

    async def stdin_writer() -> None:
        try:
            async with write_reader:
                async for message in write_reader:
                    data = message.message.model_dump_json(by_alias=True, exclude_unset=True) + "\n"
                    await process.stdin.send(data.encode("utf-8"))
        except (anyio.ClosedResourceError, anyio.BrokenResourceError, OSError):
            read_writer.close()  # the process is gone: let pending requests end now

    async with anyio.create_task_group() as pumps:
        pumps.start_soon(stdout_reader)
        pumps.start_soon(stdin_writer)
        try:
            yield _guard((read_stream, write_stream))
        finally:
            pumps.cancel_scope.cancel()
            read_stream.close()
            write_stream.close()


async def _poll_exit(process: Any, timeout_s: float) -> bool:
    """Did the process exit within the time? (Polls ``returncode``: ``wait()`` would also
    wait for pipes a surviving child may still hold.)"""
    import anyio

    with anyio.move_on_after(timeout_s):
        while process.returncode is None:
            await anyio.sleep(_POLL_S)
    return process.returncode is not None


async def _shut_down(process: Any) -> None:
    """Close stdin (the MCP way to ask for exit), then terminate, then kill after 5 s.

    On POSIX the server runs in its own process group and the whole group is signalled,
    so children it started don't outlive it.
    """
    await _close(process.stdin)
    if sys.platform != "win32":
        if not await _poll_exit(process, _STDIN_GRACE_S):
            from mcp.os.posix.utilities import terminate_posix_process_tree

            await terminate_posix_process_tree(process, _KILL_AFTER_S)
        else:
            # The leader is gone; make sure nothing it started lingers in its group.
            _signal_group(process.pid)
    elif not await _poll_exit(process, _STDIN_GRACE_S):  # pragma: no cover - Windows
        process.terminate()
        if not await _poll_exit(process, _KILL_AFTER_S):
            process.kill()
    if not await _poll_exit(process, _REAP_S):
        logger.warning("mcp server process %d is still alive after kill; abandoning it", process.pid)


def _signal_group(pgid: int) -> None:
    import os
    import signal

    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


async def _release(process: Any) -> None:
    """Close every pipe and the subprocess transport, so nothing warns at GC."""
    import anyio

    for stream in (process.stdin, process.stdout, process.stderr):
        await _close(stream)
    with anyio.move_on_after(_REAP_S):
        await process.aclose()
    transport = getattr(getattr(process, "_process", None), "_transport", None)
    close = getattr(transport, "close", None)
    if callable(close):
        try:
            close()
        except PermissionError:
            pass


async def _close(stream: Any) -> None:
    import anyio

    if stream is None:
        return
    try:
        await stream.aclose()
    except (OSError, anyio.BrokenResourceError, anyio.ClosedResourceError):
        pass
