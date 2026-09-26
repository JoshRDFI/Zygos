"""zygos doctor: passive runtime validation (RFC-0003 §6).

Local-state-only by default; --probe opts into a bounded active ping of the
primary route. Stability: Experimental.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable

from zygos.config.loader import primary_route_credentialed
from zygos.errors import PluginError
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.bootstrap import RuntimeAssembly
from zygos.voice.contract import SttHealth, TtsHealth

GpuQuery = Callable[[], "str | None"]
_NVIDIA_SMI = ["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
               "--format=csv,noheader,nounits"]


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


def query_gpu() -> str | None:
    try:
        done = subprocess.run(_NVIDIA_SMI, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_gpu(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    parts = [p.strip() for p in raw.strip().splitlines()[0].split(",")]
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        return None
    name, total, free = parts
    return f"{name}: {total} MiB total, {free} MiB free"


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


def _voice_device_checks(runtime: RuntimeAssembly, gpu_query: GpuQuery) -> list[DoctorCheck]:
    if runtime.voice_service is None:
        return []
    snap = runtime.voice_service.snapshot()
    checks = [_device_check(d, h) for d, h in (("tts", snap.tts), ("stt", snap.stt)) if h is not None]
    gpu = parse_gpu(gpu_query())
    if gpu is not None:
        checks.append(DoctorCheck("gpu", True, gpu))
    return checks


async def run_doctor(
    runtime: RuntimeAssembly, *, probe: bool = False, gpu_query: GpuQuery = query_gpu
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

    checks.extend(_voice_device_checks(runtime, gpu_query))

    if probe:
        context = runtime.new_context()
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        try:
            await runtime.model_service.generate(context, request)
            checks.append(DoctorCheck("probe", True, "primary route responded"))
        except Exception as error:  # noqa: BLE001 - any failure is a failed check
            checks.append(DoctorCheck("probe", False, f"probe failed: {error}"))

    return DoctorReport(checks=tuple(checks))
