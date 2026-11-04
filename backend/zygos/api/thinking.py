"""Per-turn native thinking: resolve the effective ``think`` value (RFC-0012 §1, §3).

Precedence: the turn's request, then the session's sticky choice, then the
configured default. A ``True`` that the routed model cannot honour is forced to
``False`` and reported with the checker's reason.

Stability: Experimental.
"""

from __future__ import annotations

THINKING_PREFIX = "Let me think about that."


async def resolve_think(session, deps, requested: bool | None) -> tuple[bool | None, str | None]:
    """Return ``(effective, unsupported_reason)`` for this turn."""
    value = requested
    if value is None:
        value = session.think
    if value is None:
        value = deps.think_default
    if value is True and deps.thinking_support is not None:
        support = await deps.thinking_support.check(deps.model_service.select_model())
        if not support.supported:
            return False, support.reason
    return value, None


async def send_think_state(session, deps) -> None:
    """Enqueue ``control:think.state {enabled, supported, reason}`` (RFC-0012 §2)."""
    from zygos.api.frames import CONTROL, Frame

    enabled = session.think if session.think is not None else deps.think_default is True
    supported, reason = True, None
    if deps.thinking_support is not None:
        support = await deps.thinking_support.check(deps.model_service.select_model())
        supported, reason = support.supported, support.reason
    session.enqueue(Frame(channel=CONTROL, type="think.state",
                          payload={"enabled": enabled, "supported": supported, "reason": reason}))
