"""zygos doctor: passive runtime validation (RFC-0003 §6).

Local-state-only by default; --probe opts into a bounded active ping of the
primary route. Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass

from zygos.config.loader import primary_route_credentialed
from zygos.errors import PluginError
from zygos.providers.types import GenerationRequest, Message
from zygos.runtime.bootstrap import RuntimeAssembly


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)


async def run_doctor(runtime: RuntimeAssembly, *, probe: bool = False) -> DoctorReport:
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

    if probe:
        context = runtime.new_context()
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        try:
            await runtime.model_service.generate(context, request)
            checks.append(DoctorCheck("probe", True, "primary route responded"))
        except Exception as error:  # noqa: BLE001 - any failure is a failed check
            checks.append(DoctorCheck("probe", False, f"probe failed: {error}"))

    return DoctorReport(checks=tuple(checks))
