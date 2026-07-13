"""run_command tool: sandboxed arbitrary-argv subprocess with streaming stdout.

Mirrors eval/codeexec.py sandbox idioms (no shell=True; new session -> killpg on exit;
optional rlimits; scrubbed env; DEVNULL stdin). Honest threat model: guards accidental
exposure + local hardening, not a determined attacker. Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path
from typing import AsyncIterator

from pydantic import BaseModel, ConfigDict, Field

from zygos.errors import ToolError
from zygos.tools.types import BaseTool, ToolContext, ToolMeta

try:
    import resource   # POSIX only
except ImportError:   # pragma: no cover
    resource = None

_SAFE_ENV = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")


def _kill_process_group(proc) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):   # pragma: no cover
        try:
            proc.kill()
        except ProcessLookupError:
            pass


class RunCommandInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    argv: list[str] = Field(
        description="Command and arguments as a list (e.g. ['ls', '-la']); executed without a shell.")
    cwd: str | None = Field(
        default=None, description="Working directory relative to the tool's root; defaults to the root.")
    env: dict[str, str] | None = Field(
        default=None, description="Extra environment variables to add to the scrubbed base environment.")


class RunCommandOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    exit_code: int
    stdout: str
    stderr: str


class RunCommandTool(BaseTool):
    def __init__(
        self,
        root: Path,
        *,
        max_output_bytes: int = 1_048_576,
        cpu_seconds: int | None = None,
        address_space_bytes: int | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._root = Path(root)
        self._max_output_bytes = max_output_bytes
        self._cpu_seconds = cpu_seconds
        self._address_space_bytes = address_space_bytes
        self.meta = ToolMeta(
            name="run_command",
            description="Run a command (given as an argv list, no shell) sandboxed under the tool's "
                        "root directory. Use to execute a program and capture its output. Executes a "
                        "subprocess (side effect).",
            input_model=RunCommandInput,
            output_model=RunCommandOutput,
            permission="ask",
            timeout_s=timeout_s,
        )

    def _resolve_cwd(self, cwd: str | None) -> Path:
        root_r = self._root.resolve()
        if cwd is None:
            return root_r
        target = (root_r / cwd).resolve()
        if target != root_r and root_r not in target.parents:
            raise ToolError(f"cwd escapes root: {cwd!r}")
        return target

    def _build_env(self, extra: dict[str, str] | None) -> dict[str, str]:
        env = {k: os.environ[k] for k in _SAFE_ENV if k in os.environ}
        if extra:
            env.update(extra)
        return env

    def _preexec(self):
        cpu, addr = self._cpu_seconds, self._address_space_bytes
        def _apply() -> None:
            if resource is None:   # pragma: no cover
                return
            if cpu is not None:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            if addr is not None:
                resource.setrlimit(resource.RLIMIT_AS, (addr, addr))
        return _apply

    async def _spawn(self, input: RunCommandInput):
        if not input.argv:
            raise ToolError("argv must be non-empty")
        cwd = self._resolve_cwd(input.cwd)
        return await asyncio.create_subprocess_exec(
            *input.argv,
            cwd=str(cwd),
            env=self._build_env(input.env),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=self._preexec(),
            start_new_session=True,
        )

    def _cap(self, data: bytes) -> str:
        return data[: self._max_output_bytes].decode("utf-8", errors="replace")

    async def execute(self, input: RunCommandInput, ctx: ToolContext) -> dict:
        proc = await self._spawn(input)
        try:
            out, err = await proc.communicate()
        except asyncio.CancelledError:
            _kill_process_group(proc)
            await proc.wait()
            raise
        return {"exit_code": proc.returncode, "stdout": self._cap(out), "stderr": self._cap(err)}

    async def execute_stream(
        self, input: RunCommandInput, ctx: ToolContext
    ) -> AsyncIterator:
        proc = await self._spawn(input)
        out_chunks: list[bytes] = []
        total = 0
        stderr_task = (
            asyncio.ensure_future(proc.stderr.read()) if proc.stderr is not None else None
        )
        try:
            assert proc.stdout is not None
            async for line in proc.stdout:
                if total < self._max_output_bytes:
                    take = line[: self._max_output_bytes - total]
                    out_chunks.append(take)
                    yield take.decode("utf-8", errors="replace")
                total += len(line)
            await proc.wait()
            err = await stderr_task if stderr_task is not None else b""
            yield {
                "exit_code": proc.returncode,
                "stdout": self._cap(b"".join(out_chunks)),
                "stderr": self._cap(err),
            }
        except asyncio.CancelledError:
            _kill_process_group(proc)
            await proc.wait()
            raise
        finally:
            if stderr_task is not None and not stderr_task.done():
                stderr_task.cancel()
            if proc.returncode is None:
                _kill_process_group(proc)
                try:
                    await proc.wait()
                except ProcessLookupError:   # pragma: no cover
                    pass
