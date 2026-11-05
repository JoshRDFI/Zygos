"""resolve_think: per-turn effective `think` (RFC-0012 §1, §3)."""

from types import SimpleNamespace

import pytest

from zygos.api.thinking import THINKING_PREFIX, resolve_think
from zygos.services.router import RouteChoice
from zygos.thinking.support import ThinkingSupport


class _Model:
    def turn_route(self): return None
    def select_model(self, classification=None):
        return RouteChoice("fake", "m")


class _Checker:
    def __init__(self, support):
        self.support = support
        self.calls = []

    async def check(self, route):
        self.calls.append(route)
        return self.support


def _deps(default=False, checker=None):
    return SimpleNamespace(think_default=default, thinking_support=checker,
                           model_service=_Model())


def _session(think=None):
    return SimpleNamespace(think=think)


def test_prefix_copy_is_verbatim():
    assert THINKING_PREFIX == "Let me think about that."


@pytest.mark.parametrize("requested, session_think, default, expected", [
    (True, False, False, True),
    (False, True, True, False),
    (None, True, False, True),
    (None, False, True, False),
    (None, None, True, True),
    (None, None, False, False),
    (None, None, None, None),
])
async def test_resolve_precedence(requested, session_think, default, expected):
    effective, reason = await resolve_think(_session(session_think), _deps(default), requested)
    assert effective is expected
    assert reason is None


async def test_resolve_unsupported_forces_false_with_reason():
    checker = _Checker(ThinkingSupport(supported=False, reason="m can't think"))
    effective, reason = await resolve_think(_session(), _deps(False, checker), True)
    assert (effective, reason) == (False, "m can't think")
    assert checker.calls == [RouteChoice("fake", "m")]


async def test_resolve_supported_keeps_true():
    checker = _Checker(ThinkingSupport(supported=True))
    assert await resolve_think(_session(), _deps(False, checker), True) == (True, None)


@pytest.mark.parametrize("requested, default", [(False, False), (None, False), (None, None)])
async def test_resolve_false_never_checks(requested, default):
    checker = _Checker(ThinkingSupport(supported=False, reason="x"))
    effective, reason = await resolve_think(_session(), _deps(default, checker), requested)
    assert reason is None
    assert checker.calls == []


class _UnroutableModel:
    def turn_route(self): return None
    def select_model(self, *a, **k):
        from zygos.errors import ProviderUnavailable
        raise ProviderUnavailable("No eligible provider routes", provider="router")


def _unroutable_deps():
    return SimpleNamespace(think_default=False, model_service=_UnroutableModel(),
                           thinking_support=_Checker(ThinkingSupport(supported=True)))


async def test_resolve_think_unroutable_model():
    result = await resolve_think(_session(), _unroutable_deps(), True)
    assert result == (False, "couldn't check the model")


async def test_think_state_unroutable_model():
    from zygos.api.thinking import send_think_state
    session = SimpleNamespace(think=None, enqueue=lambda f: sent.append(f))
    sent = []
    await send_think_state(session, _unroutable_deps())
    assert sent[0].payload == {"enabled": False, "supported": False,
                               "reason": "couldn't check the model"}
