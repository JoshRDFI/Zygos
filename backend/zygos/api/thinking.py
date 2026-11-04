"""Per-turn native thinking: resolve the effective ``think`` value (RFC-0012 §1, §3).

Precedence: the turn's request, then the session's sticky choice, then the
configured default. A ``True`` that the routed model cannot honour is forced to
``False`` and reported with the checker's reason.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from zygos.thinking.support import ThinkingSupport, check_selected

THINKING_PREFIX = "Let me think about that."


async def _check_support(deps) -> ThinkingSupport:
    """Route + support check that never raises (an unroutable model is unsupported)."""
    return await check_selected(deps.thinking_support, deps.model_service.select_model)


async def resolve_think(session, deps, requested: bool | None) -> tuple[bool | None, str | None]:
    """Return ``(effective, unsupported_reason)`` for this turn."""
    value = requested
    if value is None:
        value = session.think
    if value is None:
        value = deps.think_default
    if value is True and deps.thinking_support is not None:
        support = await _check_support(deps)
        if not support.supported:
            return False, support.reason
    return value, None


def _enqueue_state(session, deps, supported: bool, reason: str | None) -> None:
    from zygos.api.frames import CONTROL, Frame

    enabled = session.think if session.think is not None else deps.think_default is True
    session.think_support_sent = (supported, reason)
    session.enqueue(Frame(channel=CONTROL, type="think.state",
                          payload={"enabled": enabled, "supported": supported, "reason": reason}))


async def send_think_state(session, deps) -> None:
    """Enqueue ``control:think.state {enabled, supported, reason}`` (RFC-0012 §2).

    Always re-checks support (a cache hit once a probe has succeeded) and always
    sends; the sent ``(supported, reason)`` is kept on the session."""
    supported, reason = True, None
    if deps.thinking_support is not None:
        support = await _check_support(deps)
        supported, reason = support.supported, support.reason
    _enqueue_state(session, deps, supported, reason)


async def announce_if_changed(session, deps) -> None:
    """Re-check support; send ``think.state`` only if ``(supported, reason)`` changed
    since the last one sent (RFC-0012 §2: sent "when support changes")."""
    if getattr(deps, "thinking_support", None) is None:
        return
    support = await _check_support(deps)
    if (support.supported, support.reason) == getattr(session, "think_support_sent", None):
        return
    _enqueue_state(session, deps, support.supported, support.reason)


def schedule_think_state(session, deps, *, only_if_changed: bool = False) -> asyncio.Task:
    """Run a think.state send off the caller's path (the probe can take up to
    PROBE_TIMEOUT_S; the WS reader and barge-in must not wait on it).

    The task is held on ``session.think_state_task`` (no GC, cancellable on
    teardown). An explicit send supersedes a pending one; a change re-check
    defers to a pending send, which reports the current value anyway."""
    prev = getattr(session, "think_state_task", None)
    if prev is not None and not prev.done():
        if only_if_changed:
            return prev
        prev.cancel()
    coro = announce_if_changed(session, deps) if only_if_changed else send_think_state(session, deps)
    task = asyncio.create_task(coro)
    session.think_state_task = task
    return task
