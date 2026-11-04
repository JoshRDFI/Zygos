"""Async "is this backend there?" checks (RFC-0014 sections 2, 4).

Every check returns a ``Check`` and never raises (cancellation excepted).
The only subprocess is ``<llama-server> --version`` -- no shell, bounded.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from pydantic import BaseModel

from zygos.providers.types import PROBE_TIMEOUT_S

VERSION_TIMEOUT_S = 5.0


class Check(BaseModel):
    ok: bool
    detail: str


def _reason(exc: BaseException) -> str:
    text = str(exc).strip()
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


async def check_ollama(client: httpx.AsyncClient, base_url: str) -> Check:
    url = base_url.rstrip("/")
    try:
        resp = await client.get(f"{url}/api/version", timeout=PROBE_TIMEOUT_S)
        if resp.status_code != 200:
            return Check(ok=False, detail=f"Ollama at {url} answered HTTP {resp.status_code}")
        version = resp.json()["version"]
        return Check(ok=True, detail=f"Ollama {version} at {url}")
    except Exception as exc:  # noqa: BLE001 - checks never raise
        return Check(ok=False, detail=f"can't reach Ollama at {url}: {_reason(exc)}")


class VllmModel(BaseModel):
    """One model a vLLM server serves; ``max_model_len`` when its body states it."""

    id: str
    max_model_len: int | None = None


def _max_len(entry: dict) -> int | None:
    v = entry.get("max_model_len")
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else None


async def read_vllm(client: httpx.AsyncClient, base_url: str) -> tuple[Check, list[VllmModel]]:
    """``GET <base_url>/models``: the served models, or a not-ok Check saying why."""
    url = base_url.rstrip("/")
    try:
        resp = await client.get(f"{url}/models", timeout=PROBE_TIMEOUT_S)
        if resp.status_code != 200:
            return Check(ok=False, detail=f"vLLM at {url} answered HTTP {resp.status_code}"), []
        models = [VllmModel(id=str(m["id"]), max_model_len=_max_len(m)) for m in resp.json()["data"]]
        return Check(ok=True, detail=f"{len(models)} models served at {url}"), models
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"can't read models from {url}: {_reason(exc)}"), []


async def check_vllm(client: httpx.AsyncClient, base_url: str) -> tuple[Check, list[str]]:
    check, models = await read_vllm(client, base_url)
    return check, [m.id for m in models]


Runner = Callable[[list[str]], Awaitable[tuple[bytes, bytes]]]


async def _run_version(cmd: list[str]) -> tuple[bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        return await asyncio.wait_for(proc.communicate(), VERSION_TIMEOUT_S)
    except BaseException:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await asyncio.shield(proc.wait())
        raise


async def check_llama_server(path: str | None, *, run: Runner = _run_version) -> Check:
    if not path:
        return Check(ok=False, detail="llama-server path not set")
    try:
        p = Path(path)
        if p.is_dir():
            return Check(ok=False, detail=f"{path} is a directory, not llama-server")
        if not p.exists():
            return Check(ok=False, detail=f"{path} not found")
        if not os.access(p, os.X_OK):
            return Check(ok=False, detail=f"{path} is not executable")
        out, err = await asyncio.wait_for(run([path, "--version"]), VERSION_TIMEOUT_S + 1.0)
        text = (out + b"\n" + err).decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line.strip():
                return Check(ok=True, detail=line.strip())
        return Check(ok=False, detail="llama-server printed no version")
    except asyncio.TimeoutError:
        return Check(ok=False, detail="llama-server didn't answer --version within 5 s")
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"can't run llama-server: {_reason(exc)}")


def count_gguf(models_dir: str | None) -> Check:
    if not models_dir:
        return Check(ok=False, detail="models folder not set")
    try:
        root = Path(models_dir)
        if not root.is_dir():
            return Check(ok=False, detail=f"{models_dir} is not a folder")
        try:
            with os.scandir(root):
                pass
        except OSError as exc:
            return Check(ok=False, detail=f"can't read {models_dir}: {exc.strerror or _reason(exc)}")
        n = 0
        for _dirpath, _dirs, files in os.walk(root, onerror=lambda _e: None):
            n += sum(1 for f in files if f.lower().endswith(".gguf"))
        noun = "GGUF file" if n == 1 else "GGUF files"
        return Check(ok=True, detail=f"{n} {noun} in {models_dir}")
    except Exception as exc:  # noqa: BLE001
        return Check(ok=False, detail=f"can't read {models_dir}: {_reason(exc)}")
