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

from zygos.errors import ConfigError
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.manifest import Manifest, runtime_manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zygos", description="Zygos runtime inspection")
    parser.add_argument("--config", type=Path, default=None, help="Path to a config YAML")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("inspect", help="Render the runtime manifest")
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


async def _amain(args: argparse.Namespace) -> int:
    runtime = build_runtime(args.config)
    try:
        if args.command == "inspect":
            print(render_manifest(runtime_manifest(runtime)))
            return 0
        return 2
    finally:
        await runtime.aclose()


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return asyncio.run(_amain(args))
    except ConfigError as error:
        print(f"zygos: configuration error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
