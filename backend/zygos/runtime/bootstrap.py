"""Composition root (RFC-0001 §3). Stability: Experimental.

The ONLY module allowed to construct concrete service implementations.
It may only construct and connect — any logic beyond assembly is a
review-blocking smell.
"""

from dataclasses import dataclass
from pathlib import Path

from zygos.config.loader import load_config
from zygos.config.schema import ZygosConfig
from zygos.plugins.resolver import PluginRegistry


@dataclass(frozen=True)
class RuntimeAssembly:
    config: ZygosConfig
    plugins: PluginRegistry


def build_runtime(config_path: Path | None = None) -> RuntimeAssembly:
    config = load_config(config_path)
    return RuntimeAssembly(config=config, plugins=PluginRegistry(config.plugins))
