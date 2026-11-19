"""The MCP permission decision: config rules only tighten, trust is per tool fingerprint."""

from __future__ import annotations

from zygos.mcp.permission import mcp_decision, seen_fingerprint, trust_state
from zygos.mcp.store import TrustEntry, fingerprint
from zygos.mcp.types import SeenTool
from zygos.tools.permissions import Rule

TOOL = "archon__find_tasks"
SEEN = SeenTool(name="find_tasks", description="Find tasks.", input_schema={"type": "object"})


def _entry(seen: SeenTool) -> TrustEntry:
    return TrustEntry(
        server="archon", tool=TOOL, fingerprint=seen_fingerprint(seen),
        description=seen.description, input_schema=seen.input_schema, via="tool",
    )


def test_deny_rule_beats_trust():
    rules = [Rule(pattern="archon__*", decision="deny")]
    assert mcp_decision(TOOL, rules, trusted=True) == "deny"


def test_ask_rule_makes_untrusted():
    rules = [Rule(pattern="archon__*", decision="ask")]
    assert mcp_decision(TOOL, rules, trusted=True) == "not_trusted"
    # deny anywhere in the list wins over an earlier ask
    both = [Rule(pattern="*", decision="ask"), Rule(pattern=TOOL, decision="deny")]
    assert mcp_decision(TOOL, both, trusted=True) == "deny"


def test_allow_rule_ignored():
    rules = [Rule(pattern="*", decision="allow")]
    assert mcp_decision(TOOL, rules, trusted=False) == "not_trusted"
    assert mcp_decision(TOOL, rules, trusted=True) == "allow"
    assert mcp_decision(TOOL, [], trusted=True) == "allow"
    assert mcp_decision(TOOL, [Rule(pattern="other", decision="deny")], trusted=True) == "allow"


def test_trust_state_changed():
    entries = {TOOL: _entry(SEEN)}
    assert trust_state(TOOL, SEEN, entries) == "trusted"
    changed = SEEN.model_copy(update={"description": "Find tasks. Also delete them."})
    assert trust_state(TOOL, changed, entries) == "changed"
    schema_changed = SEEN.model_copy(update={"input_schema": {"type": "object", "properties": {"x": {}}}})
    assert trust_state(TOOL, schema_changed, entries) == "changed"
    assert trust_state(TOOL, SEEN, {}) == "not_trusted"


def test_seen_fingerprint_uses_server_tool_name():
    assert seen_fingerprint(SEEN) == fingerprint("find_tasks", "Find tasks.", {"type": "object"})


def test_rule_forces_ask_true_for_ask_rule():
    from zygos.mcp.permission import rule_forces_ask

    assert rule_forces_ask(TOOL, [Rule(pattern="archon__*", decision="ask")]) is True
    assert rule_forces_ask(TOOL, [Rule(pattern="other__*", decision="ask")]) is False
    assert rule_forces_ask(TOOL, []) is False


def test_rule_forces_ask_false_when_deny_also_matches():
    from zygos.mcp.permission import rule_forces_ask

    rules = [Rule(pattern="*", decision="ask"), Rule(pattern=TOOL, decision="deny")]
    assert rule_forces_ask(TOOL, rules) is False


def test_claims_maps_known_hints():
    from zygos.mcp.permission import claims

    assert claims({"readOnlyHint": True, "title": "x", "destructiveHint": False}) == ["read-only"]
    every = {"openWorldHint": True, "idempotentHint": True, "destructiveHint": True, "readOnlyHint": True}
    assert claims(every) == ["read-only", "destructive", "idempotent", "reaches outside this machine"]
    assert claims({}) == []
