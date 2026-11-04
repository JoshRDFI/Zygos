"""The Backends page / doctor view: settings plus live checks (RFC-0014 sections 2, 10).

No web-framework imports. Checks never raise; a down backend is a not-ok ``Check``.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import httpx
from pydantic import BaseModel

from zygos.backends.addresses import AddressSource, resolve_address, restart_required, routed
from zygos.backends.checks import Check, check_llama_server, check_ollama, check_vllm, count_gguf
from zygos.backends.settings import BackendsSettings
from zygos.config.schema import ZygosConfig

__all__ = ["AddressSource", "BackendsView", "build_view", "ollama_address", "restart_required",
           "uses_ollama", "uses_vllm"]


class LlamaCppView(BaseModel):
    server: Check
    models: Check


class VllmView(BaseModel):
    check: Check
    served: list[str]


class BackendsView(BaseModel):
    settings: BackendsSettings
    ollama: Check | None  # None: no route uses Ollama and no address is recorded
    llamacpp: LlamaCppView
    vllm: VllmView | None  # None: no route uses vLLM and none is recorded
    address_sources: dict[str, AddressSource]
    restart_required: bool


def uses_ollama(settings: BackendsSettings, config: ZygosConfig) -> bool:
    return bool(settings.ollama.base_url) or "ollama" in routed(config)


def uses_vllm(settings: BackendsSettings, config: ZygosConfig) -> bool:
    return bool(settings.vllm) or "vllm" in routed(config)


def ollama_address(settings: BackendsSettings, config: ZygosConfig) -> str:
    return resolve_address(config, "ollama", settings)[0]


async def _ollama_check(
    client: httpx.AsyncClient, settings: BackendsSettings, config: ZygosConfig, probe: bool
) -> Check | None:
    if not uses_ollama(settings, config):
        return None
    if not probe:
        return Check(ok=True, detail="not probed")
    return await check_ollama(client, ollama_address(settings, config))


async def _vllm_view(
    client: httpx.AsyncClient, settings: BackendsSettings, config: ZygosConfig
) -> VllmView | None:
    if not uses_vllm(settings, config):
        return None
    check, served = await check_vllm(client, resolve_address(config, "vllm", settings)[0])
    return VllmView(check=check, served=served)


async def build_view(
    settings: BackendsSettings,
    client: httpx.AsyncClient,
    *,
    config: ZygosConfig,
    address_sources: Mapping[str, AddressSource],
    addresses_at_start: Mapping[str, str],
    probe_ollama: bool = True,
) -> BackendsView:
    lc = settings.llamacpp
    ollama, server, models, vllm = await asyncio.gather(
        _ollama_check(client, settings, config, probe_ollama),
        check_llama_server(lc.server_path),
        asyncio.to_thread(count_gguf, lc.models_dir),
        _vllm_view(client, settings, config),
    )
    return BackendsView(
        settings=settings,
        ollama=ollama,
        llamacpp=LlamaCppView(server=server, models=models),
        vllm=vllm,
        address_sources=dict(address_sources),
        restart_required=restart_required(settings, config, addresses_at_start),
    )
