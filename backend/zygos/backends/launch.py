"""Parsing of user-typed llama-server launch text (RFC-0014 sections 2, 4).

The text is split with ``shlex.split`` and never passed to a shell.

Stability: Experimental.
"""

from __future__ import annotations

import shlex
from typing import Literal

from pydantic import BaseModel, ConfigDict

ZYGOS_FLAGS: frozenset[str] = frozenset(
    {
        "-m", "--model", "--host", "--port", "-a", "--alias", "--mmproj",
        "-hf", "--hf-repo", "-hfr", "-hff", "--hf-file", "-mu", "--model-url",
        "-mm", "--mmproj-url",
    }
)


class LaunchError(ValueError):
    """Launch text that cannot be accepted."""


def parse_launch(text: str) -> list[str]:
    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        raise LaunchError(f"can't read the launch settings: {exc}") from exc
    for token in tokens:
        flag = token.split("=", 1)[0] if token.startswith("-") else token
        if flag in ZYGOS_FLAGS:
            raise LaunchError(f"{flag} is set by Zygos — remove it")
    return tokens


class LaunchSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    ctx_size: int | None = None
    n_gpu_layers: int | Literal["all", "auto"] | None = None
    cache_type_k: str | None = None
    cache_type_v: str | None = None
    n_cpu_moe: int | None = None
    parallel: int | None = None
    no_kv_offload: bool = False
    jinja_off: bool = False


_VALUE_FLAGS = {
    "-c": "ctx_size", "--ctx-size": "ctx_size",
    "-ngl": "n_gpu_layers", "--n-gpu-layers": "n_gpu_layers", "--gpu-layers": "n_gpu_layers",
    "-ctk": "cache_type_k", "--cache-type-k": "cache_type_k",
    "-ctv": "cache_type_v", "--cache-type-v": "cache_type_v",
    "--n-cpu-moe": "n_cpu_moe", "-ncmoe": "n_cpu_moe",
    "-np": "parallel", "--parallel": "parallel",
}
_BOOL_FLAGS = {
    "--no-kv-offload": "no_kv_offload", "-nkvo": "no_kv_offload",
    "--no-jinja": "jinja_off",
}
_INT_FIELDS = {"ctx_size", "n_cpu_moe", "parallel"}


def _int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _layers(value: str) -> int | Literal["all", "auto"] | None:
    if value in ("all", "auto"):
        return value
    n = _int(value)
    if n is None:
        return None
    return "all" if n == -1 or n >= 999 else n


def read_launch(args: list[str]) -> LaunchSettings:
    found: dict[str, object] = {}
    i = 0
    while i < len(args):
        token = args[i]
        i += 1
        flag, eq, inline = token.partition("=")
        if token in _BOOL_FLAGS:
            found[_BOOL_FLAGS[token]] = True
            continue
        field = _VALUE_FLAGS.get(flag)
        if field is None:
            continue
        if eq:
            value = inline
        elif i < len(args):
            value = args[i]
            i += 1
        else:
            continue
        if field in _INT_FIELDS:
            found[field] = _int(value)
        elif field == "n_gpu_layers":
            found[field] = _layers(value)
        else:
            found[field] = value
    return LaunchSettings(**found)
