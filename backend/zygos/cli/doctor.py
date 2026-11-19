"""zygos doctor: passive runtime validation (RFC-0003 §6).

Local-state-only by default; --probe opts into a bounded active ping of the
primary route. Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from zygos.backends.addresses import resolve_address
from zygos.backends.view import build_view, restart_required, uses_ollama, uses_vllm
from zygos.config.loader import primary_route_credentialed
from zygos.errors import PluginError
from zygos.hardware.describe import describe_hardware
from zygos.hardware.probe import HardwareProbe, run_nvidia_smi
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.bootstrap import RuntimeAssembly
from zygos.services.model import CONFIG_ORDER
from zygos.services.router import RouteChoice
from zygos.voice.contract import SttHealth, TtsHealth

GpuQuery = Callable[[], "str | None"]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    warn: bool = False   # informational problem: rendered [warn], never fails the report


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


def _device_check(direction: str, health: SttHealth | TtsHealth) -> DoctorCheck:
    name = f"voice_{direction}_device"
    if health.device == health.requested_device:
        if (not health.alive and health.requested_device != "cpu"
                and health.fallback_reason is None):
            # The CLI doctor never starts voice (only api/app.py does), so the
            # launch spec's device is unconfirmed: a broken GPU venv, driver/CUDA
            # mismatch, or ORT silently landing on CPU would all look identical
            # here until something actually starts the worker.
            return DoctorCheck(
                name, True,
                f"{health.engine}: requested {health.requested_device} — not verified "
                "(voice not started); check GET /runtime on a running server, or run: "
                "zygos voice setup-gpu to re-verify",
                warn=True,
            )
        return DoctorCheck(name, True, f"{health.engine} on {health.device}")
    return DoctorCheck(
        name, True,
        f"{health.engine}: requested {health.requested_device}, running on {health.device}"
        f" — {health.fallback_reason or 'no reason reported'}",
        warn=True,
    )


def _voice_device_checks(runtime: RuntimeAssembly) -> list[DoctorCheck]:
    if runtime.voice_service is None:
        return []
    snap = runtime.voice_service.snapshot()
    return [_device_check(d, h) for d, h in (("tts", snap.tts), ("stt", snap.stt)) if h is not None]


def _hardware_check(runtime: RuntimeAssembly, gpu_query: GpuQuery) -> DoctorCheck:
    # A fresh probe fed by the injected gpu_query (default: the real nvidia-smi)
    # with the runtime's configured models dir; runtime.hardware's cached scan
    # is left alone. No GPU is a warning, never a failure.
    snap = HardwareProbe(run_nvidia_smi=gpu_query,
                         models_dir=runtime.config.models.ollama_models_dir).scan()
    return DoctorCheck("hardware", True, describe_hardware(snap), warn=not snap.gpus)


# Providers whose installed models the catalog lists (ModelCatalog.installed()).
_LISTED_PROVIDERS = frozenset({"ollama", "vllm"})


def _default_model_check(runtime: RuntimeAssembly) -> DoctorCheck:
    """The model that answers turns (RFC-0013 §4): passive -- the saved choice,
    the config, and the catalog's last-known installed set; no network."""
    status = runtime.default_status()
    route = f"{status.route.provider}/{status.route.model}"
    if status.ignored is not None:
        saved = f"{status.ignored.provider}/{status.ignored.model}"
        return DoctorCheck(
            "default_model", True,
            f"saved default {saved} ignored: {status.reason}; using {route}", warn=True)
    if status.source == "saved" and status.route.provider in _LISTED_PROVIDERS \
            and runtime.model_catalog.installed(status.route.provider) is None:
        # This process never listed the provider, so a deleted model can't be told
        # apart from an installed one; say so rather than give a false all-clear.
        return DoctorCheck("default_model", True,
                           f"{route} (saved; installation not checked — run with the server or use --probe)")
    return DoctorCheck("default_model", True, f"{route} ({status.source})")


def _secrets_check(runtime: RuntimeAssembly) -> list[DoctorCheck]:
    """One passive read of the secret store: never writes, never shows a value."""
    try:
        return _secrets_lines(runtime)
    except Exception as exc:  # noqa: BLE001 - never abort the report; never str(exc)
        return [DoctorCheck("secrets", False, f"unexpected error ({type(exc).__name__})")]


def _secrets_lines(runtime: RuntimeAssembly) -> list[DoctorCheck]:
    from zygos.secrets import SecretStoreError
    from zygos.secrets.file_store import path_exists
    from zygos.secrets.resolve import ENCRYPTED_FILE, REASON_PROVISIONAL

    handle = runtime.secrets
    status = handle.status()
    file_store = handle.file_store()
    if not status.available:
        why = status.why_unavailable or "no secret store"
        if handle.has_saved() is not False:  # None: a record exists but can't be read
            return [DoctorCheck("secrets", False, why)]
        return [DoctorCheck("secrets", True, f"not available — {why}", warn=True)]
    if status.backend == ENCRYPTED_FILE:
        try:
            if path_exists(file_store.enc_path):
                handle.get("provider:doctor-probe")  # read-only integrity check
        except SecretStoreError as exc:
            return [DoctorCheck("secrets", False, str(exc))]
    out: list[DoctorCheck] = []
    if status.reason == REASON_PROVISIONAL:
        out.append(DoctorCheck("secrets", True, f"{status.backend} ({REASON_PROVISIONAL})"))
    else:
        out.append(DoctorCheck("secrets", True, f"{status.backend} ({status.reason}) — {status.location}"))
    if file_store.key_file_loose():
        key = file_store.key_path
        out.append(DoctorCheck(
            "secrets_key_file", True,
            f"{key} is readable by other users; run chmod 600 {key}", warn=True,
        ))
    return out


_MCP_READ_BUSY_S = 5.0
_MCP_PROBE_S = 5.0
_MCP_TOOL_WARN_OVER = 20
_SECRET_HINT = "switch it off and on (zygos mcp off/on {name}) after unlocking the secret store"


def _mcp_installed() -> bool:
    try:
        return importlib.util.find_spec("mcp") is not None
    except (ImportError, ValueError):
        return False


async def _default_list_remote(*args: Any, **kwargs: Any) -> Any:
    from zygos.mcp.remote import list_remote  # imports the SDK only when called

    return await list_remote(*args, **kwargs)


def _local_detail(state: Any) -> str:
    when = ""
    if state.status_at is not None:
        when = f" (as of {datetime.fromtimestamp(state.status_at).strftime('%H:%M')}, from zygos serve)"
    if state.status == "not_started":
        return "not started — zygos serve starts it"
    text = state.status.replace("_", " ") + when
    if state.status == "stopped" and state.exit_code is not None:
        text = f"stopped — exit {state.exit_code}"
        last = (state.stderr_tail or "").strip().splitlines()
        if last:
            text += f": {last[-1]}"
    elif state.detail:
        text += f" — {state.detail}"
    return text


async def _probe_remote(spec: Any, state: Any, list_remote: Callable[..., Any], timeout_s: float) -> tuple[str, bool]:
    limit = min(spec.timeout_s, timeout_s)
    try:
        # Header values are not read: a server that needs them is reported not reachable.
        result = await asyncio.wait_for(
            list_remote(spec, {}, era=state.era, discover=state.discover), limit)
    except TimeoutError:
        return f"not reachable: no answer within {limit:g} s", True
    except Exception as exc:  # noqa: BLE001 - doctor never aborts; type only, no text
        return f"not reachable: {type(exc).__name__}", True
    n = len(result.tools)
    return f"reachable, {n} tool{'s' if n != 1 else ''}", False


async def _mcp_checks(
    runtime: RuntimeAssembly, probe: bool, list_remote: Callable[..., Any] | None,
    mcp_installed: Callable[[], bool], probe_timeout_s: float,
) -> list[DoctorCheck]:
    """MCP servers as recorded; connects only with ``probe``. Never raises."""
    from zygos.mcp.config import address, describe, zygos_tool_name
    from zygos.mcp.offered import checked, with_clashes
    from zygos.mcp.store import McpStoreUnavailable
    from zygos.mcp.supervisor import NO_MCP, TOOL_COUNT_WARNING

    store = runtime.mcp.store.strict_reader(busy_timeout_s=_MCP_READ_BUSY_S)
    try:
        def read() -> tuple[Any, Any, Any]:
            servers = store.servers()
            if not servers:
                return servers, None, None
            return servers, store.off(), {n: store.state(n) for n in servers}

        servers, off, states = await asyncio.to_thread(read)
    except McpStoreUnavailable:
        return [DoctorCheck("mcp", True, "the MCP record can't be read right now — try again", warn=True)]
    except Exception as exc:  # noqa: BLE001
        return [DoctorCheck("mcp", True, f"the MCP record can't be read ({type(exc).__name__})", warn=True)]
    if not servers:
        return []
    out: list[DoctorCheck] = []
    installed = mcp_installed()
    if not installed:
        out.append(DoctorCheck("mcp", True, NO_MCP, warn=True))
    connect = list_remote or _default_list_remote
    for name in sorted(servers):
        spec, state = servers[name], states[name]
        if spec.transport == "stdio":
            detail, warn = _local_detail(state), state.status in ("stopped", "failed")
            if state.status == "failed" and "secret" in (state.detail or "").lower():
                detail += f" — {_SECRET_HINT.format(name=name)}"
        elif probe and (installed or list_remote is not None):
            note, warn = await _probe_remote(spec, state, connect, probe_timeout_s)
            detail = f"{spec.url} (protocol {state.era or 'not known yet'}) — {note}"
        else:
            detail = f"{spec.url} (protocol {state.era or 'not known yet'})"
            warn = state.status in ("unreachable", "failed")
            if warn and state.detail:
                detail += f" — {state.status}: {state.detail}"
            if state.status == "failed" and "secret" in (state.detail or "").lower():
                detail += f" — {_SECRET_HINT.format(name=name)}"
        out.append(DoctorCheck(f"mcp:{name}", True, detail, warn=warn))
    tools_by = {n: checked(s.tools) for n, s in states.items()}
    tools_by.update(with_clashes(tools_by))
    count = sum(
        1 for n in servers if f"server:{n}" not in off
        for t in tools_by.get(n, [])
        if t.problem is None and f"tool:{zygos_tool_name(n, t.name)}" not in off
    )
    too_many = count > _MCP_TOOL_WARN_OVER
    out.append(DoctorCheck("mcp_tools", True,
                           f"{count} on" + (f" — {TOOL_COUNT_WARNING}" if too_many else ""), warn=too_many))
    return out


async def _backend_checks(runtime: RuntimeAssembly) -> list[DoctorCheck]:
    """Optional backends (RFC-0014): shown only when set up; problems warn, never fail."""
    settings = runtime.backends.get()
    config = runtime.config
    lc = settings.llamacpp
    out: list[DoctorCheck] = []
    show_ollama = uses_ollama(settings, config)
    show_llama = bool(lc.server_path or lc.models_dir)
    if not (show_ollama or show_llama or uses_vllm(settings, config)):
        return out
    view = await build_view(
        settings, runtime.http_client, config=config,
        address_sources=runtime.address_sources, addresses_at_start=runtime.addresses_at_start,
        probe_ollama=False,  # doctor is passive: the Ollama address is shown, not probed
    )
    if show_ollama:
        url, source = resolve_address(config, "ollama", settings)
        out.append(DoctorCheck("ollama_address", True, f"{url} (from {source})"))
    if show_llama:
        out.append(DoctorCheck("llamacpp_server", True, view.llamacpp.server.detail,
                               warn=not view.llamacpp.server.ok))
        out.append(DoctorCheck("llamacpp_models", True, view.llamacpp.models.detail,
                               warn=not view.llamacpp.models.ok))
    if view.vllm is not None:
        served = f" — serving: {', '.join(view.vllm.served)}" if view.vllm.served else ""
        out.append(DoctorCheck("vllm", True, view.vllm.check.detail + served,
                               warn=not view.vllm.check.ok))
    if restart_required(settings, config, runtime.addresses_at_start):
        out.append(DoctorCheck(
            "backends_restart", True,
            "a saved backend address differs from the one in use: restart Zygos to apply it",
            warn=True,
        ))
    return out


async def run_doctor(
    runtime: RuntimeAssembly, *, probe: bool = False, gpu_query: GpuQuery = run_nvidia_smi,
    list_remote: Callable[..., Any] | None = None,
    mcp_installed: Callable[[], bool] = _mcp_installed,
    probe_timeout_s: float = _MCP_PROBE_S,
) -> DoctorReport:
    config = runtime.config
    checks: list[DoctorCheck] = []

    primary = config.providers.primary
    if primary_route_credentialed(config):
        checks.append(DoctorCheck("primary_credentialed", True, f"{primary.provider}:{primary.model}"))
    else:
        checks.append(
            DoctorCheck(
                "primary_credentialed",
                False,
                f"primary route {primary.provider} is missing required credentials",
            )
        )

    unresolved: list[str] = []
    for kind, entries in config.plugins.items():
        for name in entries:
            try:
                runtime.plugins.resolve(kind, name)
            except PluginError as error:
                unresolved.append(f"{kind}/{name}: {error}")
    checks.append(
        DoctorCheck(
            "plugins_resolve",
            not unresolved,
            "all declared plugins resolve" if not unresolved else "; ".join(unresolved),
        )
    )

    snapshot = runtime.capability_registry.snapshot()
    missing = [c.value for c in config.required_capabilities if not snapshot.bindings.get(c)]
    checks.append(
        DoctorCheck(
            "required_capabilities",
            not missing,
            "all required capabilities covered" if not missing else f"no binding for: {', '.join(missing)}",
        )
    )

    prefs = runtime.preferences.get()
    if prefs.is_empty:
        checks.append(DoctorCheck(
            "personalization", True,
            "not set: run `zygos personalize` to set your name and the assistant's",
            warn=True,
        ))
    else:
        checks.append(DoctorCheck(
            "personalization", True,
            f"set (assistant: {prefs.assistant_name or '-'}, user: {prefs.user_name or '-'})",
        ))

    from zygos.home import stray_data_dir, stray_message, zygos_home

    home = zygos_home()
    checks.append(DoctorCheck("zygos_home", True, f"{home.root} ({home.source})"))
    stray = stray_data_dir()
    if stray is not None:
        checks.append(DoctorCheck("stray_data_folder", True, stray_message(stray), warn=True))

    checks.extend(_secrets_check(runtime))
    checks.extend(await _mcp_checks(runtime, probe, list_remote, mcp_installed, probe_timeout_s))
    checks.append(_default_model_check(runtime))
    checks.append(_hardware_check(runtime, gpu_query))
    checks.extend(_voice_device_checks(runtime))
    checks.extend(await _backend_checks(runtime))

    if probe:
        context = runtime.new_context()
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        answered: list[RouteChoice] = []
        saved = runtime.model_service.turn_route()
        try:
            await runtime.model_service.generate(
                context, request, route=saved if saved is not None else CONFIG_ORDER,
                on_route=answered.append)
            who = answered[-1] if answered else (saved or runtime.model_service.select_model())
            note = " (the saved default)" if saved is not None and who == saved else ""
            checks.append(DoctorCheck("probe", True, f"{who.provider}/{who.model} responded{note}"))
        except Exception as error:  # noqa: BLE001 - any failure is a failed check
            checks.append(DoctorCheck("probe", False, f"probe failed: {error}"))

    return DoctorReport(checks=tuple(checks))
