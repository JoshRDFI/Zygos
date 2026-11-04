"""zygos CLI adapter (RFC-0003 §6).

A thin adapter: build the runtime, render pure manifest/doctor data, print.
Any logic beyond adapting belongs in the runtime, not here.

Stability: Experimental.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError

from zygos.cli.doctor import DoctorReport, run_doctor
from zygos.errors import ConfigError
from zygos.personalization import PERSONALIZATION_FIELDS, Personalization
from zygos.personalization.onboarding import run_onboarding
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.manifest import Manifest, runtime_manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zygos", description="Zygos runtime inspection")
    parser.add_argument("--config", type=Path, default=None, help="Path to a config YAML")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("inspect", help="Render the runtime manifest")
    doctor = subcommands.add_parser("doctor", help="Validate the wired runtime")
    doctor.add_argument("--probe", action="store_true", help="Actively ping the primary route")
    serve = subcommands.add_parser("serve", help="Run the HTTP/WebSocket server")
    serve.add_argument("--host", default=None, help="Bind host (default: config.server.host)")
    serve.add_argument("--port", type=int, default=None, help="Bind port (default: config.server.port)")
    voice = subcommands.add_parser("voice", help="Voice tooling")
    voice_cmds = voice.add_subparsers(dest="voice_command", required=True)
    setup_gpu = voice_cmds.add_parser("setup-gpu", help="Build the GPU TTS sidecar venv")
    setup_gpu.add_argument("--force", action="store_true", help="Delete and rebuild the venv")
    personalize = subcommands.add_parser("personalize", help="Set your name and the assistant's")
    personalize_cmds = personalize.add_subparsers(dest="personalize_command", required=False)
    personalize_cmds.add_parser("show", help="Show the saved personalization")
    personalize_cmds.add_parser("clear", help="Remove all personalization")
    set_cmd = personalize_cmds.add_parser("set", help="Set individual fields directly")
    for field in PERSONALIZATION_FIELDS:
        set_cmd.add_argument(f"--{field.replace('_', '-')}", dest=field, default=None)
    return parser


async def _personalize(runtime, args: argparse.Namespace) -> int:
    store = runtime.preferences
    sub = args.personalize_command
    if sub is None:
        try:
            await run_onboarding(
                runtime.new_context(), runtime.model_service, store, ask=input, say=print
            )
        except KeyboardInterrupt:
            return 130
        return 0
    if sub == "show":
        prefs = store.get()
        lines = [f"{f}: {getattr(prefs, f)}" for f in PERSONALIZATION_FIELDS if getattr(prefs, f)]
        print("\n".join(lines) if lines else "Not personalized.")
        return 0
    if sub == "clear":
        store.set(Personalization())
        print("Personalization cleared.")
        return 0
    given = {f: getattr(args, f) for f in PERSONALIZATION_FIELDS if getattr(args, f) is not None}
    if not given:
        _build_parser().error("personalize set: give at least one field flag")
    try:
        store.set(Personalization(**{**store.get().model_dump(), **given}))
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "value"
        print(f"zygos: invalid {field}: {first['msg']}", file=sys.stderr)
        return 1
    return 0


def render_manifest(manifest: Manifest) -> str:
    lines = [
        f"Zygos runtime (stage: {manifest.lifecycle_stage})",
        f"  version: {manifest.versions.get('zygos', 'unknown')} "
        f"(python {manifest.versions.get('python', '?')})",
        f"  primary route: {manifest.primary_route.provider}:{manifest.primary_route.model}",
    ]
    for route in manifest.fallback_routes:
        lines.append(f"  fallback route: {route.provider}:{route.model}")
    lines.append("  capabilities:")
    if not manifest.capabilities:
        lines.append("    (none registered)")
    for capability, bindings in sorted(manifest.capabilities.items(), key=lambda kv: kv[0].value):
        rendered = ", ".join(
            f"{b.provider}(p{b.priority},{'healthy' if b.healthy else 'unhealthy'})"
            for b in bindings
        )
        lines.append(f"    {capability.value}: {rendered}")
    lines.append("  plugins:")
    for plugin in manifest.plugins:
        lines.append(f"    {plugin.kind}/{plugin.name} -> {plugin.module}")
    return "\n".join(lines)


def render_doctor(report: DoctorReport) -> str:
    lines = ["zygos doctor:"]
    for check in report.checks:
        mark = "FAIL" if not check.ok else ("warn" if check.warn else "ok  ")
        lines.append(f"  [{mark}] {check.name}: {check.detail}")
    lines.append("healthy" if report.ok else "PROBLEMS FOUND")
    return "\n".join(lines)


async def _amain(args: argparse.Namespace) -> int:
    runtime = build_runtime(args.config)
    try:
        if args.command == "inspect":
            print(render_manifest(runtime_manifest(runtime)))
            return 0
        if args.command == "doctor":
            report = await run_doctor(runtime, probe=args.probe)
            print(render_doctor(report))
            return 0 if report.ok else 1
        if args.command == "personalize":
            return await _personalize(runtime, args)
        return 2
    finally:
        await runtime.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "voice":
            from zygos.voice import gpu_setup

            return gpu_setup.setup_gpu(force=args.force)
        if args.command == "serve":
            from zygos.api.app import run_server

            runtime = build_runtime(args.config)
            if runtime.preferences.get().is_empty:
                print(
                    "zygos: not personalized yet: run `zygos personalize` "
                    "to set your name and the assistant's.",
                    file=sys.stderr,
                )
            host = args.host if args.host is not None else runtime.config.server.host
            port = args.port if args.port is not None else runtime.config.server.port
            run_server(runtime, host=host, port=port)
            return 0
        return asyncio.run(_amain(args))
    except ConfigError as error:
        print(f"zygos: configuration error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
