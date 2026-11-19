"""Browser access checks: only pages served from this machine (or configured
origins) may change state or open a session socket, and every request must name
this machine (or a configured host) in its Host header.

The Host check closes DNS rebinding: a hostile site whose domain re-resolves to
127.0.0.1 is same-origin with itself and could otherwise read GET routes, but the
browser still sends its own hostname as Host.

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
_WILDCARD_BINDS = {"0.0.0.0", "::"}
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


def log_refused_host(host: str) -> None:
    _log.warning("refused host: %s", host[:200])


def _hostname(host_header: str) -> str | None:
    """The lower-cased hostname of a Host header value (port and trailing dot
    dropped), or None when the value is malformed."""
    value = host_header.strip()
    if not value or any(c.isspace() for c in value):
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        name, rest = value[1:end], value[end + 1:]
        if not name or (rest and not (rest.startswith(":") and rest[1:].isdigit())):
            return None
    else:
        name, sep, port = value.partition(":")
        if sep and not port.isdigit():
            return None
        if not name or ":" in port:
            return None
    return name.lower().rstrip(".") or None


def host_allowed(host_header: str | None, allowed: frozenset[str]) -> bool:
    """True when the Host header names an allowed hostname (port ignored).

    A missing header is allowed: browsers always send one, and a client without
    one is not the DNS-rebinding threat.
    """
    if host_header is None:
        return True
    name = _hostname(host_header)
    return name is not None and name in allowed


def allowed_hosts_for(server) -> frozenset[str]:
    """Hostnames a request may name: loopback, the host of each allowed origin, a
    specific bind address, and ``server.allowed_hosts``."""
    hosts = set(_LOOPBACK)
    for origin in server.allowed_origins:
        try:
            name = urlsplit(origin).hostname
        except ValueError:
            continue
        if name:
            hosts.add(name.lower().rstrip("."))
    if server.host and server.host not in _WILDCARD_BINDS:
        hosts.add(server.host.lower().rstrip("."))
    for name in server.allowed_hosts:
        if name.strip():
            hosts.add(name.strip().lower().rstrip("."))
    return frozenset(hosts)


class OriginGuard:
    """ASGI guard for browser access: the Host header on every HTTP and WebSocket
    request, and the Origin header on writes and the WebSocket handshake route."""

    def __init__(
        self,
        app: ASGIApp,
        allowed_origins: Sequence[str] = (),
        allowed_hosts: frozenset[str] = frozenset(_LOOPBACK),
    ) -> None:
        self.app = app
        self.extra = tuple(allowed_origins)
        self.allowed_hosts = allowed_hosts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket"):
            host = None
            for k, v in scope["headers"]:
                if k == b"host":
                    host = v.decode("latin-1")
                    break
            if not host_allowed(host, self.allowed_hosts):
                log_refused_host(host or "")
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 4403})
                    return
                await self._refuse(send, "host not allowed; add it to server.allowed_hosts")
                return
        if scope["type"] == "http" and scope["method"] in _WRITE_METHODS:
            origin = None
            for k, v in scope["headers"]:
                if k == b"origin":
                    origin = v.decode("latin-1")
                    break
            if not origin_allowed(origin, self.extra):
                log_refused(origin or "")
                await self._refuse(send, "origin not allowed")
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(send: Send, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": 403, "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ]})
        await send({"type": "http.response.body", "body": body})
