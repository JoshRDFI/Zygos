"""The Backends page / doctor view: settings plus live checks (RFC-0014 sections 2, 10).

No web-framework imports. Checks never raise; a down backend is a not-ok ``Check``.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Literal

import httpx
from pydantic import BaseModel

from zygos.backends.checks import Check, check_llama_server, check_ollama, check_vllm, count_gguf
from zygos.backends.settings import BackendsSettings
from zygos.providers.base import DEFAULT_BASE_URLS

AddressSource = Literal["backends", "config", "default"]


class LlamaCppView(BaseModel):
    server: Check
    models: Check


class VllmView(BaseModel):
    check: Check
    served: list[str]


class BackendsView(BaseModel):
    settings: BackendsSettings
    ollama: Check
    llamacpp: LlamaCppView
    vllm: VllmView | None
    address_sources: dict[str, AddressSource]
    restart_required: bool


def restart_required(settings: BackendsSettings, addresses_at_start: Mapping[str, str]) -> bool:
    """A record address that differs from the one in force since startup."""
    recorded = {"ollama": settings.ollama.base_url}
    if settings.vllm:
        recorded["vllm"] = settings.vllm[0].base_url
    return any(url and addresses_at_start.get(name) != url for name, url in recorded.items())


def ollama_address(
    settings: BackendsSettings, addresses_at_start: Mapping[str, str]
) -> str:
    return (
        settings.ollama.base_url
        or addresses_at_start.get("ollama")
        or DEFAULT_BASE_URLS["ollama"]
    )


async def _ollama_check(
    client: httpx.AsyncClient,
    settings: BackendsSettings,
    addresses_at_start: Mapping[str, str],
    probe: bool,
) -> Check:
    if not probe:
        return Check(ok=True, detail="not probed")
    return await check_ollama(client, ollama_address(settings, addresses_at_start))


async def build_view(
    settings: BackendsSettings,
    client: httpx.AsyncClient,
    address_sources: Mapping[str, AddressSource],
    addresses_at_start: Mapping[str, str],
    *,
    probe_ollama: bool = True,
) -> BackendsView:
    lc = settings.llamacpp
    vllm_checks = (
        check_vllm(client, settings.vllm[0].base_url) if settings.vllm else None
    )
    ollama, server, models = await asyncio.gather(
        _ollama_check(client, settings, addresses_at_start, probe_ollama),
        check_llama_server(lc.server_path),
        asyncio.to_thread(count_gguf, lc.models_dir),
    )
    vllm: VllmView | None = None
    if vllm_checks is not None:
        check, served = await vllm_checks
        vllm = VllmView(check=check, served=served)
    return BackendsView(
        settings=settings,
        ollama=ollama,
        llamacpp=LlamaCppView(server=server, models=models),
        vllm=vllm,
        address_sources=dict(address_sources),
        restart_required=restart_required(settings, addresses_at_start),
    )
