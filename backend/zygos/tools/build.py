"""ToolBuildContext — the uniform construction input for config-declared tools (M8 C3).

A tool's `from_config(ctx)` reads what it needs (a sandbox `workspace`, its own `settings`),
mirroring how providers are built from `(settings, client)`. Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolBuildContext:
    workspace: Path                      # resolved ToolsConfig.workspace_root
    settings: Mapping[str, Any]          # this tool's entry from ToolsConfig.settings (may be {})
