"""Interactive WebSocket permission resolver (RFC-0007 §7).

Turns a tool's `ask` decision into a `tools:permission` frame and awaits the client's
`tools:permission_response`, correlated by `call_id`. A timeout, a disconnect, or an
unknown/absent session resolves to `deny` (the deny-floor honest-threat-model). Routes to
the right socket via `ctx.exec.session_id`.

Every prompt sent is closed by one `tools:permission.result` frame naming its outcome.
An `allow` that asks to trust the tool (or its server) records that trust when the
prompt offered it; a failed save still allows the call, and says so. When the session
is speaking, one short line asks the user to look at the screen. Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from zygos.api.frames import TOOLS, Frame
from zygos.api.session import Session, SessionRegistry
from zygos.tools.permissions import PermissionRequest
from zygos.tools.types import PermissionDecision, ToolContext

logger = logging.getLogger("zygos.api.permission")

TrustScope = Literal["tool", "server"]
Outcome = Literal[
    "allowed", "trusted_tool", "trusted_server", "denied", "timed_out", "cancelled", "trust_failed",
]


@dataclass(frozen=True)
class PromptAnswer:
    """The user's answer to one prompt. ``trust`` only counts with ``allow``."""

    decision: Literal["allow", "deny"]
    trust: TrustScope | None = None


class WebSocketPromptResolver:
    def __init__(
        self,
        registry: SessionRegistry,
        timeout_s: float,
        *,
        trust: Callable[[str, str], Awaitable[bool]] | None = None,
        announce: Callable[[Session, str], Any] | None = None,
    ) -> None:
        self._registry = registry
        self._timeout_s = timeout_s
        self._trust = trust
        self._announce = announce
        self._announcing: set[asyncio.Future[Any]] = set()  # strong refs until done

    async def resolve(self, req: PermissionRequest, ctx: ToolContext) -> PermissionDecision:
        session_id = ctx.exec.session_id
        session = self._registry.get(session_id) if session_id else None
        if session is None or not session.connected:
            return "deny"
        fut: asyncio.Future[PromptAnswer] = asyncio.get_running_loop().create_future()
        session.pending_permissions[req.call_id] = fut
        cancel_wait = asyncio.ensure_future(ctx.wait_cancelled())
        outcome: Outcome = "cancelled"
        prompted = False
        try:
            # The tool's details may set can_trust; they never replace the prompt's own keys.
            session.enqueue(Frame(channel=TOOLS, type="permission", payload={
                "can_trust": False, **req.details,
                "call_id": req.call_id, "tool": req.tool, "args_summary": req.args_summary,
                "expires_in_s": self._timeout_s,
            }))
            prompted = True
            self._speak(session, req)
            # Race the client's response against the turn's cancellation. A barge-in
            # or control:cancel trips the CancelToken; without observing it here the
            # tool would stay parked until the timeout, freezing the WS reader loop
            # that awaits the cancelled turn (9774f63d). An abandoned turn's
            # permission is moot, so cancellation (like a timeout) denies.
            await asyncio.wait({fut, cancel_wait}, timeout=self._timeout_s,
                               return_when=asyncio.FIRST_COMPLETED)
            if not fut.done():
                outcome = "cancelled" if cancel_wait.done() else "timed_out"
                return "deny"
            # A cancelled or failed future, or anything that is not an answer (the
            # socket's teardown settles pending prompts this way), denies.
            if fut.cancelled() or fut.exception() is not None:
                return "deny"
            answer = fut.result()
            if not isinstance(answer, PromptAnswer):
                return "deny"
            if answer.decision != "allow":
                outcome = "denied"
                return "deny"
            outcome = await self._record_trust(req, answer)
            return "allow"
        except asyncio.CancelledError:
            outcome = "cancelled"
            return "deny"
        finally:
            cancel_wait.cancel()
            session.pending_permissions.pop(req.call_id, None)
            if prompted:
                # Harmless when the socket is gone: the queue is never drained.
                session.enqueue(Frame(channel=TOOLS, type="permission.result", payload={
                    "call_id": req.call_id, "outcome": outcome,
                }))

    async def _record_trust(self, req: PermissionRequest, answer: PromptAnswer) -> Outcome:
        """Record trust when the prompt offered it and the user asked; else a plain allow."""
        if answer.trust is None or not req.details.get("can_trust") or self._trust is None:
            return "allowed"
        try:
            saved = await self._trust(req.tool, answer.trust)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the user said yes; the call still runs
            logger.warning("could not record trust for %r (%s)", req.tool, type(exc).__name__)
            saved = False
        if saved is not True:
            return "trust_failed"
        return "trusted_tool" if answer.trust == "tool" else "trusted_server"

    def _speak(self, session: Session, req: PermissionRequest) -> None:
        """Ask aloud once per prompt when the session is speaking. Never delays or
        breaks the prompt."""
        if self._announce is None or not session.speak:
            return
        name = req.details.get("server_tool") or req.tool
        text = f"I need your OK on screen to use {str(name).replace('_', ' ')}."
        try:
            started = self._announce(session, text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("permission announce failed (%s)", type(exc).__name__)
            return
        if isinstance(started, asyncio.Future):
            self._announcing.add(started)
            started.add_done_callback(self._announce_done)

    def _announce_done(self, fut: asyncio.Future[Any]) -> None:
        self._announcing.discard(fut)
        if not fut.cancelled() and (exc := fut.exception()) is not None:
            logger.warning("permission announce failed (%s)", type(exc).__name__)
