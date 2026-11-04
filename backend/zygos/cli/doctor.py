"""zygos doctor: passive runtime validation (RFC-0003 §6).

Local-state-only by default; --probe opts into a bounded active ping of the
primary route. Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from zygos.config.loader import primary_route_credentialed
from zygos.errors import PluginError
from zygos.hardware.describe import describe_hardware
from zygos.hardware.probe import HardwareProbe, run_nvidia_smi
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.bootstrap import RuntimeAssembly
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


async def run_doctor(
    runtime: RuntimeAssembly, *, probe: bool = False, gpu_query: GpuQuery = run_nvidia_smi
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

    checks.append(_hardware_check(runtime, gpu_query))
    checks.extend(_voice_device_checks(runtime))

    if probe:
        context = runtime.new_context()
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        try:
            await runtime.model_service.generate(context, request)
            checks.append(DoctorCheck("probe", True, "primary route responded"))
        except Exception as error:  # noqa: BLE001 - any failure is a failed check
            checks.append(DoctorCheck("probe", False, f"probe failed: {error}"))

    return DoctorReport(checks=tuple(checks))
