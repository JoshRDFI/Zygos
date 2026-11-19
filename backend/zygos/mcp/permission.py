"""The permission decision for MCP tools (RFC-0015 §5; spec "Untrusted tools in 1a").

Config rules can only tighten an MCP tool: any matching ``deny`` denies, any matching
``ask`` makes it "not trusted", ``allow`` rules are ignored. Otherwise trust decides;
trust is per tool and pinned to a fingerprint of the tool as it was trusted.
Pure: no I/O, no SDK import.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from fnmatch import fnmatch
from typing import Any, Literal

from zygos.mcp.store import TrustEntry, fingerprint
from zygos.mcp.types import SeenTool
from zygos.tools.permissions import Rule
from zygos.tools.service import McpDecision

__all__ = ["McpDecision", "claims", "mcp_decision", "rule_forces_ask", "seen_fingerprint", "trust_state"]

TrustState = Literal["trusted", "not_trusted", "changed"]


def mcp_decision(tool_name: str, rules: Sequence[Rule], trusted: bool) -> McpDecision:
    matching = {rule.decision for rule in rules if fnmatch(tool_name, rule.pattern)}
    if "deny" in matching:
        return "deny"
    if "ask" in matching:
        return "not_trusted"  # a config ask rule prompts every time; trust cannot loosen it
    return "allow" if trusted else "not_trusted"


def rule_forces_ask(tool_name: str, rules: Sequence[Rule]) -> bool:
    """True when an ``ask`` rule matches the tool and no ``deny`` rule does: trusting it
    would change nothing, since the rule asks every time."""
    matching = {rule.decision for rule in rules if fnmatch(tool_name, rule.pattern)}
    return "ask" in matching and "deny" not in matching


_CLAIMS = (
    ("readOnlyHint", "read-only"),
    ("destructiveHint", "destructive"),
    ("idempotentHint", "idempotent"),
    ("openWorldHint", "reaches outside this machine"),
)


def claims(annotations: Mapping[str, Any]) -> list[str]:
    """What the server says about a tool, in plain words. Hints are the server's own
    claims, never verified."""
    return [word for key, word in _CLAIMS if annotations.get(key) is True]


def seen_fingerprint(seen: SeenTool) -> str:
    """The fingerprint trust is pinned to: the server's own tool name, description, schema."""
    return fingerprint(seen.name, seen.description, seen.input_schema)


def trust_state(tool: str, seen: SeenTool, entries: Mapping[str, TrustEntry]) -> TrustState:
    """``tool`` is the zygos tool name; ``changed`` = trusted once, but not as it is now."""
    entry = entries.get(tool)
    if entry is None:
        return "not_trusted"
    return "trusted" if entry.fingerprint == seen_fingerprint(seen) else "changed"
