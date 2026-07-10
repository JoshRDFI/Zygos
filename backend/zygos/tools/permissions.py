"""Permission policy + resolver seam (ARCHITECTURE §Tool Contract; v1 semantics preserved).

Static `PermissionPolicy` decides allow/deny/ask; a tool resolving to `ask` delegates to an
injected `PermissionResolver`. The headless default (M8 wires a WebSocket resolver later) is
`DenyingResolver` — nobody to ask means deny. Stability: Experimental.
"""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from zygos.tools.types import PermissionDecision, ToolContext, ToolMeta


class PermissionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    args_summary: dict[str, Any] = {}   # shallow; for a human prompt in M8. No secrets.
    run_id: str
    call_id: str


class Rule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pattern: str                        # fnmatch glob over the tool name
    decision: PermissionDecision


class PermissionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    rules: list[Rule] = []
    default: PermissionDecision = "allow"

    def decide(self, meta: ToolMeta) -> PermissionDecision:
        # meta.permission == "deny" is a hard floor — a rule cannot loosen it.
        if meta.permission == "deny":
            return "deny"
        # A tool self-declaring "ask" is honored regardless of rules.
        if meta.permission == "ask":
            return "ask"
        # meta.permission == "allow": rules may tighten (allow -> ask/deny); first match wins.
        for rule in self.rules:
            if fnmatch(meta.name, rule.pattern):
                return rule.decision
        return self.default


@runtime_checkable
class PermissionResolver(Protocol):
    """Resolves an `ask` decision to a terminal allow/deny. Never returns `ask`."""

    async def resolve(self, req: PermissionRequest, ctx: ToolContext) -> PermissionDecision: ...


class DenyingResolver:
    """Headless default: nobody to ask, so deny."""

    async def resolve(self, req: PermissionRequest, ctx: ToolContext) -> PermissionDecision:
        return "deny"


class AllowingResolver:
    """Dev/test/eval convenience: auto-approve `ask` tools."""

    async def resolve(self, req: PermissionRequest, ctx: ToolContext) -> PermissionDecision:
        return "allow"
