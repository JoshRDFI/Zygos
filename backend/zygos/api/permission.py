"""Interactive WebSocket permission resolver (RFC-0007 §7).

Turns a tool's `ask` decision into a `tools:permission` frame and awaits the client's
`tools:permission_response`, correlated by `call_id`. A timeout, a disconnect, or an
unknown/absent session resolves to `deny` (the deny-floor honest-threat-model). Routes to
the right socket via `ctx.exec.session_id`. Stability: Experimental.
"""

from __future__ import annotations

import asyncio

from zygos.api.frames import TOOLS, Frame
from zygos.api.session import SessionRegistry
from zygos.tools.permissions import PermissionRequest
from zygos.tools.types import PermissionDecision, ToolContext


class WebSocketPromptResolver:
    def __init__(self, registry: SessionRegistry, timeout_s: float) -> None:
        self._registry = registry
        self._timeout_s = timeout_s

    async def resolve(self, req: PermissionRequest, ctx: ToolContext) -> PermissionDecision:
        session_id = ctx.exec.session_id
        session = self._registry.get(session_id) if session_id else None
        if session is None or not session.connected:
            return "deny"
        fut: asyncio.Future[PermissionDecision] = asyncio.get_running_loop().create_future()
        session.pending_permissions[req.call_id] = fut
        try:
            session.enqueue(Frame(channel=TOOLS, type="permission", payload={
                "call_id": req.call_id, "tool": req.tool, "args_summary": req.args_summary,
            }))
            return await asyncio.wait_for(fut, self._timeout_s)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return "deny"
        finally:
            session.pending_permissions.pop(req.call_id, None)
