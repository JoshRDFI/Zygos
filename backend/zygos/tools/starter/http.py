"""http_fetch tool + SSRF/URL validation. httpx is a core dependency.

Honest threat model: blocks obvious SSRF targets (loopback/private/link-local/metadata) at
request time and re-validates every redirect hop. Does NOT defend against DNS-rebinding.
Stability: Experimental.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

from zygos.errors import ToolError, ToolTransient
from zygos.tools.build import ToolBuildContext
from zygos.tools.types import BaseTool, RetryPolicy, ToolContext, ToolMeta


def _is_blocked_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    return (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_unspecified
        or addr.is_multicast
        or addr.is_reserved
    )


def _validate_url(url: str, allow_schemes: tuple[str, ...]) -> None:
    parts = urlsplit(url)
    if parts.scheme not in allow_schemes:
        raise ToolError(f"scheme not allowed: {parts.scheme!r}")
    host = parts.hostname
    if not host:
        raise ToolError(f"missing host in url: {url!r}")
    try:
        addrs = [info[4][0] for info in socket.getaddrinfo(host, None)]
    except OSError as exc:
        raise ToolTransient(f"dns resolution failed for {host!r}: {exc}")
    if not addrs or any(_is_blocked_ip(a) for a in addrs):
        raise ToolError(f"blocked host (ssrf guard): {host!r}")


class HttpFetchInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    url: str = Field(description="Absolute http(s) URL to fetch.")
    method: str = Field(default="GET", description="HTTP method, e.g. GET or POST.")
    headers: dict[str, str] = Field(default={}, description="Optional HTTP request headers.")
    body: str | None = Field(default=None, description="Optional request body for POST/PUT.")


class HttpFetchOutput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    status: int
    headers: dict[str, str]
    body: str
    truncated: bool


class HttpFetchTool(BaseTool):
    def __init__(
        self,
        *,
        allow_schemes: tuple[str, ...] = ("http", "https"),
        max_bytes: int = 2_097_152,
        max_redirects: int = 5,
        ssrf_guard: bool = True,
        timeout_s: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._allow_schemes = allow_schemes
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._ssrf_guard = ssrf_guard
        self._transport = transport
        self.meta = ToolMeta(
            name="http_fetch",
            description="Fetch an http(s) URL and return the response status, headers, and body. Use "
                        "when you need data from the web or an HTTP API. Network side effect; blocks "
                        "internal/loopback addresses.",
            input_model=HttpFetchInput,
            output_model=HttpFetchOutput,
            permission="ask",
            retry=RetryPolicy(attempts=3),
            timeout_s=timeout_s,
        )

    @classmethod
    def from_config(cls, ctx: ToolBuildContext) -> "HttpFetchTool":
        s = ctx.settings
        kwargs = {}
        if "allow_schemes" in s:
            kwargs["allow_schemes"] = tuple(s["allow_schemes"])
        for key in ("max_bytes", "max_redirects", "ssrf_guard", "timeout_s"):
            if key in s:
                kwargs[key] = s[key]
        return cls(**kwargs)

    async def execute(self, input: HttpFetchInput, ctx: ToolContext) -> dict:
        url = input.url
        content = input.body.encode("utf-8") if input.body is not None else None
        async with httpx.AsyncClient(transport=self._transport, follow_redirects=False) as client:
            for _ in range(self._max_redirects + 1):
                if self._ssrf_guard:
                    _validate_url(url, self._allow_schemes)
                try:
                    async with client.stream(
                        input.method, url, headers=input.headers, content=content
                    ) as resp:
                        if resp.is_redirect and "location" in resp.headers:
                            url = urljoin(url, resp.headers["location"])
                            continue
                        chunks: list[bytes] = []
                        total = 0
                        async for chunk in resp.aiter_bytes():
                            if total < self._max_bytes:
                                chunks.append(chunk[: self._max_bytes - total])
                            total += len(chunk)
                        return {
                            "status": resp.status_code,
                            "headers": dict(resp.headers),
                            "body": b"".join(chunks).decode("utf-8", errors="replace"),
                            "truncated": total > self._max_bytes,
                        }
                except httpx.TransportError as exc:
                    raise ToolTransient(f"transport error: {exc}")
            raise ToolError(f"too many redirects (> {self._max_redirects})")
