"""Origin check: only pages served from this machine (or configured origins)
may change state or open a session socket through a browser.

Stability: Experimental.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

_log = logging.getLogger(__name__)

_LOOPBACK = {"localhost", "127.0.0.1", "::1"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def origin_allowed(origin: str | None, extra: Sequence[str]) -> bool:
    if origin is None:
        return True
    if origin.rstrip("/") in {e.rstrip("/") for e in extra}:
        return True
    try:
        parts = urlsplit(origin)
        parts.port  # noqa: B018 - raises ValueError on a malformed port
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and parts.hostname in _LOOPBACK


def log_refused(origin: str) -> None:
    _log.warning("refused origin: %s", origin[:200])


class OriginGuard:
    def __init__(self, app: ASGIApp, allowed_origins: Sequence[str] = ()) -> None:
        self.app = app
        self.extra = tuple(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _WRITE_METHODS:
            origin = None
            for k, v in scope["headers"]:
                if k == b"origin":
                    origin = v.decode("latin-1")
                    break
            if not origin_allowed(origin, self.extra):
                log_refused(origin or "")
                body = json.dumps({"detail": "origin not allowed"}).encode()
                await send({"type": "http.response.start", "status": 403, "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
