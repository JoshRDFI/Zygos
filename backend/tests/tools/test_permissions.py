"""M5 C2 Task 3 — permission policy + resolver seam."""

import asyncio

from pydantic import BaseModel

from zygos.tools.permissions import (
    AllowingResolver,
    DenyingResolver,
    PermissionPolicy,
    PermissionRequest,
    Rule,
)
from zygos.tools.types import ToolMeta


class _In(BaseModel):
    x: int


def _meta(name="t", permission="allow"):
    return ToolMeta(name=name, description="d", input_model=_In, permission=permission)


def test_allow_tool_no_rules_allows():
    assert PermissionPolicy().decide(_meta()) == "allow"


def test_rule_can_tighten_allow_to_deny():
    p = PermissionPolicy(rules=[Rule(pattern="t", decision="deny")])
    assert p.decide(_meta(name="t")) == "deny"


def test_rule_can_tighten_allow_to_ask():
    p = PermissionPolicy(rules=[Rule(pattern="fs.*", decision="ask")])
    assert p.decide(_meta(name="fs.read")) == "ask"


def test_first_matching_rule_wins():
    p = PermissionPolicy(rules=[Rule(pattern="fs.*", decision="ask"),
                                Rule(pattern="fs.read", decision="deny")])
    assert p.decide(_meta(name="fs.read")) == "ask"  # first match


def test_default_used_when_no_rule_matches():
    p = PermissionPolicy(rules=[Rule(pattern="fs.*", decision="deny")], default="ask")
    assert p.decide(_meta(name="net.get")) == "ask"


def test_meta_deny_is_hard_floor_rule_cannot_loosen():
    p = PermissionPolicy(rules=[Rule(pattern="t", decision="allow")])
    assert p.decide(_meta(name="t", permission="deny")) == "deny"


def test_meta_ask_is_honored():
    assert PermissionPolicy().decide(_meta(permission="ask")) == "ask"


def test_resolvers_return_fixed_decisions():
    req = PermissionRequest(tool="t", run_id="r", call_id="c")
    assert asyncio.run(DenyingResolver().resolve(req, ctx=None)) == "deny"
    assert asyncio.run(AllowingResolver().resolve(req, ctx=None)) == "allow"


def test_rule_loosens_ask_to_allow():
    policy = PermissionPolicy(rules=[Rule(pattern="http_fetch", decision="allow")])
    assert policy.decide(_meta(name="http_fetch", permission="ask")) == "allow"


def test_ask_with_no_rule_stays_ask():
    policy = PermissionPolicy()
    assert policy.decide(_meta(name="write_file", permission="ask")) == "ask"


def test_rule_cannot_loosen_deny():
    policy = PermissionPolicy(rules=[Rule(pattern="danger", decision="allow")])
    assert policy.decide(_meta(name="danger", permission="deny")) == "deny"


def test_rule_still_tightens_allow():
    policy = PermissionPolicy(rules=[Rule(pattern="read_file", decision="deny")])
    assert policy.decide(_meta(name="read_file", permission="allow")) == "deny"


def test_rule_tightens_ask_to_deny():
    policy = PermissionPolicy(rules=[Rule(pattern="run_command", decision="deny")])
    assert policy.decide(_meta(name="run_command", permission="ask")) == "deny"
