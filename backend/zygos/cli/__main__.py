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

from zygos.cli.doctor import DoctorReport, run_doctor
from zygos.errors import ConfigError
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
    return parser


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
        mark = "ok  " if check.ok else "FAIL"
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
        return 2
    finally:
        await runtime.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            from zygos.api.app import run_server

            runtime = build_runtime(args.config)
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
