"""Sandboxed execution scoring for code tasks. Stability: Experimental."""

import asyncio
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass

try:
    import resource  # POSIX only
except ImportError:  # pragma: no cover
    resource = None

_FENCE = re.compile(r"```[a-zA-Z0-9_+-]*\n(.*?)```", re.DOTALL)

DEFAULT_CODE_TIMEOUT_S = 5.0
_MEM_LIMIT_BYTES = 512 * 1024 * 1024  # address-space cap for the child

# Neutralise accidental network egress at the Python level (honest threat model).
_PREAMBLE = (
    "import socket as _sock\n"
    "def _blocked(*a, **k):\n"
    "    raise RuntimeError('network disabled in code_exec sandbox')\n"
    "_sock.socket = _blocked\n"
    "_sock.create_connection = _blocked\n"
)


def extract_code(text: str) -> str:
    """Return the last fenced code block's body, else the stripped whole text."""
    blocks = _FENCE.findall(text)
    if blocks:
        return blocks[-1].strip()
    return text.strip()


@dataclass(frozen=True)
class CheckOutcome:
    passed: int
    total: int
    error: str | None = None


def _build_script(code: str, checks: tuple[str, ...]) -> str:
    return (
        _PREAMBLE
        + code
        + "\n\nimport json as _json\n"
        + f"_checks = _json.loads({json.dumps(list(checks))!r})\n"
        + "_passed = 0\n"
        + "for _c in _checks:\n"
        + "    try:\n"
        + "        exec(_c, globals())\n"
        + "        _passed += 1\n"
        + "    except Exception:\n"
        + "        pass\n"
        + "print(_json.dumps({'passed': _passed, 'total': len(_checks)}))\n"
    )


def _limits(timeout_s: float):
    def _apply() -> None:
        if resource is None:  # pragma: no cover
            return
        cpu = int(timeout_s) + 1
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_LIMIT_BYTES, _MEM_LIMIT_BYTES))
    return _apply


async def run_checks(code: str, checks: tuple[str, ...], timeout_s: float | None = None) -> CheckOutcome:
    timeout = timeout_s if timeout_s is not None else DEFAULT_CODE_TIMEOUT_S
    total = len(checks)
    script = _build_script(code, checks)
    workdir = tempfile.mkdtemp(prefix="zygos-codeexec-")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", script,
            cwd=workdir,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limits(timeout),
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return CheckOutcome(passed=0, total=total, error="timeout")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    lines = stdout.decode(errors="replace").strip().splitlines()
    if lines:
        try:
            data = json.loads(lines[-1])
            return CheckOutcome(passed=int(data["passed"]), total=int(data["total"]))
        except (ValueError, KeyError, TypeError):
            pass
    tail = stderr.decode(errors="replace").strip()[-200:]
    return CheckOutcome(passed=0, total=total, error=tail or "no output")
