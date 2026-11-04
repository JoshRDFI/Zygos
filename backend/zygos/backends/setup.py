"""Interactive backends setup (RFC-0014 section 2).

Review-before-save: nothing is written until the final confirm. ``ask`` and ``say``
are injected, like the identity onboarding. Never starts llama-server or a model.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Callable

import httpx

from zygos.backends.checks import (
    Runner,
    _run_version,
    check_llama_server,
    check_ollama,
    check_vllm,
    count_gguf,
)
from zygos.backends.addresses import resolve_address, restart_required
from zygos.backends.launch import LaunchError, parse_launch
from zygos.backends.settings import (
    BackendsSettings,
    LlamaCppBackend,
    OllamaBackend,
    VllmEndpoint,
    resolve_path,
)
from zygos.backends.store import BackendsStore
from zygos.config.schema import ZygosConfig

_INSTALL = (
    "llama.cpp isn't set up. Install it from https://github.com/ggml-org/llama.cpp "
    "(releases or build instructions), then run `zygos personalize backends`."
)


def _yes(answer: str) -> bool:
    return answer.strip().lower() in ("y", "yes")


def summarize(settings: BackendsSettings) -> list[str]:
    ll = settings.llamacpp
    llama_line = (
        "llama.cpp: not set up"
        if ll == LlamaCppBackend()
        else f"llama.cpp: server {ll.server_path or 'not set'}; models {ll.models_dir or 'not set'}; "
        f"launch settings: {ll.default_args or 'none'}"
    )
    vllm_line = f"vLLM: {settings.vllm[0].base_url}" if settings.vllm else "vLLM: not set up"
    return [f"Ollama: {settings.ollama.base_url or 'default address'}", llama_line, vllm_line]


async def _ask_llama_server(
    current: str | None, ask: Callable[[str], str], say: Callable[[str], None], run: Runner
) -> str | None:
    shown = current or "not set"
    answer = resolve_path(ask(f"llama-server path (Enter keeps {shown}): "), command=True)
    if not answer:
        if current:
            say(f"llama-server: {(await check_llama_server(current, run=run)).detail}")
        return current
    for attempt in range(2):
        check = await check_llama_server(answer, run=run)
        say(f"llama-server: {check.detail}")
        if check.ok:
            return answer
        if attempt == 0:
            answer = resolve_path(ask(f"llama-server path (Enter keeps {shown}): "), command=True)
            if not answer:
                return current
    if current:
        say("Keeping the current llama-server path.")
        return current
    say("Keeping the llama-server path unset.")
    return None


async def _ask_models_dir(
    current: str | None, ask: Callable[[str], str], say: Callable[[str], None]
) -> str | None:
    """Like the server path: a failed check is asked once more, then setup goes on."""
    prompt = f"GGUF models folder (Enter keeps {current or 'not set'}): "
    answer = resolve_path(ask(prompt))
    if not answer:
        if current:
            say(f"Models: {(await asyncio.to_thread(count_gguf, current)).detail}")
        return current
    for attempt in range(2):
        check = await asyncio.to_thread(count_gguf, answer)
        say(f"Models: {check.detail}")
        if check.ok:
            return answer
        if attempt == 0:
            answer = resolve_path(ask(prompt))
            if not answer:
                return current
    if current:
        say("Keeping the current models folder.")
        return current
    say("Keeping the models folder unset.")
    return None


def _ask_launch(current: str, ask: Callable[[str], str], say: Callable[[str], None]) -> str:
    while True:
        text = ask("Default launch settings (as typed after llama-server; Enter for none): ").strip()
        if not text:
            return current
        try:
            parse_launch(text)
        except LaunchError as exc:
            say(str(exc))
            continue
        return text


async def run_backend_setup(
    store: BackendsStore,
    client: httpx.AsyncClient,
    *,
    config: ZygosConfig,
    addresses_at_start: Mapping[str, str],
    ask: Callable[[str], str],
    say: Callable[[str], None],
    run_version: Runner = _run_version,
) -> bool:
    try:
        old = store.get()
        current_ollama_url = resolve_address(config, "ollama", old)[0]

        # 1. Ollama
        say(f"Ollama: {(await check_ollama(client, current_ollama_url)).detail}")
        answer = ask(f"Ollama address (Enter keeps {current_ollama_url}): ").strip()
        ollama = OllamaBackend(base_url=answer or old.ollama.base_url)
        if answer:
            say(f"Ollama: {(await check_ollama(client, answer)).detail}")

        # 2. llama.cpp
        llamacpp = old.llamacpp
        if _yes(ask("Do you have llama.cpp installed? [y/N]: ")):
            server = await _ask_llama_server(old.llamacpp.server_path, ask, say, run_version)
            models_dir = await _ask_models_dir(old.llamacpp.models_dir, ask, say)
            args = _ask_launch(old.llamacpp.default_args, ask, say)
            llamacpp = LlamaCppBackend(
                server_path=server,
                models_dir=models_dir,
                default_args=args,
                model_args=old.llamacpp.model_args,
            )
        elif old.llamacpp != LlamaCppBackend():
            llamacpp = LlamaCppBackend()  # saved before, now declined: drop it (on confirm)
        else:
            say(_INSTALL)

        # 3. vLLM
        vllm = old.vllm
        if _yes(ask("Do you run a vLLM server? [y/N]: ")):
            current = old.vllm[0].base_url if old.vllm else None
            answer = ask(f"vLLM address (Enter keeps {current or 'not set'}): ").strip()
            url = answer or current
            if url:
                check, ids = await check_vllm(client, url)
                say(f"vLLM: {check.detail}")
                if ids:
                    say("Models served: " + ", ".join(ids))
                vllm = [VllmEndpoint(base_url=url)]
        else:
            vllm = []

        # 4. Review and save
        new = BackendsSettings(ollama=ollama, llamacpp=llamacpp, vllm=vllm)
        say("Here is what will be saved:")
        for line in summarize(new):
            say(line)
        if not _yes(ask("Save these settings? [y/N]: ")):
            return False
        store.set(new)
        if restart_required(new, config, addresses_at_start):
            say("Restart Zygos for address changes to apply.")
        return True
    except EOFError:
        say("Nothing was saved.")
        return False
