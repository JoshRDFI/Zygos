"""MCP routes for the Tools page: list, add, remove, switch, trust, secrets, timeout,
refresh (RFC-0015).

Each route is a thin front end on ``zygos.mcp.manage``, the functions ``zygos mcp`` runs,
so the page and the CLI change the record the same way. Record and secret-store calls run
in a thread. After a write the supervisor applies it at once (``sync_now``); a local
server whose secret changed is restarted, since it reads its env only when it starts.

No response carries a secret value: secrets read ``set``, ``not set`` or ``unknown``, a
secret PUT answers with the view only, and a body that fails validation is answered by
``mcp_validation_handler`` with a reason that never quotes the input. Refusals are
``{"detail": reason}``: 404 no such server, tool or secret; 422 invalid input; 409 the
record changed since the preview; 413 the pasted text is too large; 503 the record or the
secret store is unavailable.

The Host and Origin checks are the app-wide ``OriginGuard``.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from zygos.mcp import manage
from zygos.mcp.config import validation_reason
from zygos.mcp.manage import ManageError, McpView, PlannedServer
from zygos.mcp.store import McpStoreUnavailable, SqliteMcpStore
from zygos.secrets import Presence, SecretStoreError

__all__ = ["mcp_validation_handler", "router"]

router = APIRouter(prefix="/mcp")

_T = TypeVar("_T")

_STATUS = {"not_found": 404, "invalid": 422, "conflict": 409, "too_large": 413, "unavailable": 503}
_VIEW_LIMIT_S = 5.0  # GET /mcp answers within this even when the secret store hangs
_READ_BUSY_S = 5.0  # how long a read waits for another writer before a 503
_NO_ANSWER = "the secret store didn't answer in time"
_CHANGED = "the servers changed since the preview — preview again"
_RESTARTS = "applies now; the server restarts"
_STARTING = " — starting it now; Refresh lists its tools"


# ---- bodies -----------------------------------------------------------------------------


class PlanBody(BaseModel):
    text: str


class SaveBody(BaseModel):
    text: str
    confirm: Literal[True]
    replaces: list[str] = Field(default_factory=list)  # the servers the preview said it replaces


class SecretBody(BaseModel):
    value: str


class TimeoutBody(BaseModel):
    timeout_s: Any  # checked by ``manage.set_timeout``, with the CLI's message


class PlanOut(BaseModel):
    servers: list[PlannedServer]
    problems: list[str]


class SaveOut(BaseModel):
    view: McpView
    notes: list[str]
    listing: list[str]


class NotedView(BaseModel):
    view: McpView
    notes: list[str]


# ---- shared -----------------------------------------------------------------------------


async def mcp_validation_handler(request: Request, exc: Exception) -> Response:
    """Under ``/mcp``, a body that fails validation gets the first problem without the
    rejected input (FastAPI's default 422 echoes it, and it may be a secret). Other routes
    keep the default response."""
    path = request.url.path
    if path != "/mcp" and not path.startswith("/mcp/"):
        return await request_validation_exception_handler(request, exc)  # type: ignore[arg-type]
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    reason = validation_reason(exc) if errors else "invalid request"  # type: ignore[arg-type]
    return JSONResponse(status_code=422, content={"detail": reason})


@contextmanager
def _refusals() -> Iterator[None]:
    """Shared-logic refusals and record failures as HTTP errors, worded as the CLI words them."""
    try:
        with _refusals_except_manage():
            yield
    except ManageError as exc:
        raise HTTPException(_STATUS[exc.kind], exc.reason) from None


@contextmanager
def _refusals_except_manage() -> Iterator[None]:
    """Record failures as HTTP errors (a ``ManageError`` passes through)."""
    try:
        yield
    except McpStoreUnavailable as exc:  # already a readable reason, never values
        raise HTTPException(503, str(exc)) from None
    except sqlite3.Error as exc:
        raise HTTPException(503, f"couldn't update the MCP record ({exc}); try again") from None


def _runtime(request: Request) -> Any:
    return request.app.state.runtime


def _store(request: Request) -> SqliteMcpStore:
    # Strict: an unreadable record is a 503, never "no servers".
    return _runtime(request).mcp.store.strict_reader(busy_timeout_s=_READ_BUSY_S)


async def _off_loop(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    with _refusals():
        return await asyncio.to_thread(fn, *args, **kwargs)


class _Answering:
    """The secret store as the view asks it: a failure that isn't a ``SecretStoreError``
    (a keyring backend's own error) reads ``unknown`` with its type name only, never its
    text."""

    def __init__(self, secrets: Any) -> None:
        self._secrets = secrets

    def presence(self, handle: str) -> Presence:
        try:
            return self._secrets.presence(handle)
        except SecretStoreError:
            raise  # ``manage.presence`` reports these by their own reason
        except Exception as exc:  # noqa: BLE001 - any backend failure reads "unknown"
            return Presence("unknown", type(exc).__name__)


class _NoAnswer:
    """Stands in for a secret store that didn't answer within the view's bound."""

    def presence(self, handle: str) -> Presence:
        return Presence("unknown", _NO_ANSWER)


def _in_daemon_thread(fn: Callable[[], _T]) -> asyncio.Future[_T]:
    """Run ``fn`` on a daemon thread of its own and resolve a future on this loop with its
    outcome. A read stuck on a hung keychain then never holds a thread of the shared
    default pool, and never keeps the process from exiting (pool threads are joined at
    exit; a daemon thread is not)."""
    loop = asyncio.get_running_loop()
    future: asyncio.Future[_T] = loop.create_future()

    def settle(result: Any, error: BaseException | None) -> None:
        if future.done():
            return
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)

    def run() -> None:
        result: Any = None
        error: BaseException | None = None
        try:
            result = fn()
        except BaseException as exc:  # noqa: BLE001 - handed to the awaiting view
            error = exc
        try:
            loop.call_soon_threadsafe(settle, result, error)
        except RuntimeError:
            pass  # the loop has closed: nobody is waiting for this read

    threading.Thread(target=run, name="mcp-presence", daemon=True).start()
    return future


def _retrieve(future: asyncio.Future[Any]) -> None:
    if not future.cancelled():
        future.exception()  # read by a later view or no one; never logged as unretrieved


async def _view(request: Request) -> McpView:
    """The view, bounded: when the secret store doesn't answer in time, the secrets read
    ``unknown``. One view at a time asks the secret store; while that read is still in
    flight (a locked keychain can block for long) the others read ``unknown`` at once
    rather than queue behind it. The event loop never waits on the store."""
    store = _store(request)
    state = request.app.state
    pending: asyncio.Future[McpView] | None = getattr(state, "mcp_view_pending", None)
    if pending is None or pending.done():
        secrets = _Answering(_runtime(request).secrets)
        pending = _in_daemon_thread(
            lambda: manage.list_view(store, secrets, mcp_installed=manage.mcp_installed)
        )
        pending.add_done_callback(_retrieve)
        state.mcp_view_pending = pending
        try:
            with _refusals():
                # shield: a timeout must not mark the read done while its thread still runs
                return await asyncio.wait_for(asyncio.shield(pending), _VIEW_LIMIT_S)
        except TimeoutError:
            pass
    return await _off_loop(manage.list_view, store, _NoAnswer(), mcp_installed=manage.mcp_installed)


async def _written(request: Request, *, restart: str | None = None) -> McpView:
    """Apply a record change in the running supervisor, then answer with a fresh view."""
    mcp = _runtime(request).mcp
    with _refusals():
        mcp.sync_now()
        if restart is not None:
            mcp.restart(restart)
    return await _view(request)


# ---- the view and refresh -----------------------------------------------------------------


@router.get("", response_model=McpView)
async def get_mcp(request: Request) -> McpView:
    return await _view(request)


@router.post("/refresh", response_model=McpView)
async def refresh(request: Request) -> McpView:
    with _refusals():
        await _runtime(request).mcp.refresh()
    return await _view(request)


# ---- add ------------------------------------------------------------------------------------


@router.post("/plan", response_model=PlanOut)
async def plan(body: PlanBody, request: Request) -> PlanOut:
    """What saving the pasted servers would do; saves nothing."""
    found = await _off_loop(manage.plan_add, _store(request), body.text)
    return PlanOut(servers=found.servers, problems=found.problems)


@router.post("/servers", response_model=SaveOut)
async def save_servers(body: SaveBody, request: Request) -> Any:
    """Save the pasted servers, then list each new remote one once.

    The preview is checked again: when the servers the paste would replace are no longer
    the ones the preview showed (another tab or the CLI wrote in between), nothing is
    saved. One server failing to save doesn't stop the others; when none could be saved
    the first refusal is the response, with every server's note."""
    runtime = _runtime(request)
    store = _store(request)
    found = await _off_loop(manage.plan_add, store, body.text)
    if found.problems:
        raise HTTPException(422, "; ".join(found.problems))
    if {s.name for s in found.servers if s.replaces} != set(body.replaces):
        raise HTTPException(409, _CHANGED)
    existing = await _off_loop(store.servers)
    notes: list[str] = []
    refused: list[ManageError] = []
    saved = []
    for item in found.items:
        name = item.spec.name
        try:
            with _refusals_except_manage():
                notes += await asyncio.to_thread(
                    manage.save_server, store, runtime.secrets, item, existing.get(name)
                )
        except ManageError as exc:
            refused.append(exc)
            notes.append(f"{name}: not added — {exc.reason}")
            notes += exc.notes
            continue
        saved.append(item)
    if refused and not saved:
        first = refused[0]
        return JSONResponse(status_code=_STATUS[first.kind], content={"detail": first.reason, "notes": notes})
    return await _listed(request, saved, notes)


async def _listed(request: Request, saved: list[Any], notes: list[str]) -> SaveOut:
    runtime = _runtime(request)
    store = _store(request)
    remote = [item for item in saved if item.spec.transport != "stdio"]
    list_remote = runtime.mcp.connectors.list_remote

    def list_once(item: Any) -> str:
        # Each listing runs on its own loop in a thread, as the CLI runs it, so its record
        # write never blocks this loop.
        return asyncio.run(manage.list_after_add(
            store, item.spec, item, list_remote=list_remote, mcp_installed=manage.mcp_installed,
            clock=time.time,
        ))

    outcomes = dict(zip(
        [item.spec.name for item in remote],
        await asyncio.gather(*(_off_loop(list_once, item) for item in remote)),
        strict=True,
    ))
    listing = [
        outcomes[item.spec.name] if item.spec.name in outcomes else f"{item.spec.name}: added{_STARTING}"
        for item in saved
    ]
    view = await _written(request)
    return SaveOut(view=view, notes=notes, listing=listing)


# ---- one server -------------------------------------------------------------------------
# Server names may contain "/", hence ``{name:path}``; the routes with a suffix come before
# the bare DELETE so the suffix is never read as part of a name.


@router.put("/servers/{name:path}/on", response_model=McpView)
async def server_on(name: str, request: Request) -> McpView:
    await _off_loop(manage.switch_server, _store(request), name, True, clock=time.time)
    return await _written(request)


@router.put("/servers/{name:path}/off", response_model=McpView)
async def server_off(name: str, request: Request) -> McpView:
    await _off_loop(manage.switch_server, _store(request), name, False, clock=time.time)
    return await _written(request)


@router.put("/servers/{name:path}/trust", response_model=McpView)
async def trust_server(name: str, request: Request) -> McpView:
    """Trust every tool the server shows now; tools it adds later need trusting on their own."""
    await _off_loop(manage.trust_server, _store(request), name)
    return await _written(request)


@router.delete("/servers/{name:path}/trust", response_model=McpView)
async def untrust_server(name: str, request: Request) -> McpView:
    """Withdraw the server-wide trust; tools trusted one by one stay trusted."""
    await _off_loop(manage.untrust_server, _store(request), name)
    return await _written(request)


@router.put("/servers/{name:path}/secrets/{secret}", response_model=McpView)
async def set_secret(name: str, secret: str, body: SecretBody, request: Request) -> McpView:
    """Store a new value for one of the server's secrets; the answer never carries it."""
    store, secrets = _store(request), _runtime(request).secrets

    def put() -> bool:
        manage.set_secret(store, secrets, name, secret, body.value)
        return manage.find_server(store, name).transport == "stdio"

    local = await _off_loop(put)
    return await _written(request, restart=name if local else None)


@router.put("/servers/{name:path}/timeout", response_model=NotedView)
async def set_timeout(name: str, body: TimeoutBody, request: Request) -> NotedView:
    """Set the per-call timeout; trust, on/off and the last listing are kept."""
    spec = await _off_loop(manage.set_timeout, _store(request), name, body.timeout_s)
    notes = [_RESTARTS] if spec.transport == "stdio" else []
    return NotedView(view=await _written(request), notes=notes)


@router.delete("/servers/{name:path}", response_model=NotedView)
async def remove_server(name: str, request: Request) -> NotedView:
    """Remove the server, its state, trust and on/off, then its secrets."""
    notes = await _off_loop(manage.remove_server, _store(request), _runtime(request).secrets, name)
    return NotedView(view=await _written(request), notes=notes)


# ---- one tool, by the name the model sees (``server__tool``) -----------------------------


async def _tool_action(request: Request, zname: str, action: Callable[..., Any], *args: Any) -> McpView:
    store = _store(request)

    def run() -> None:
        spec, seen = manage.find_tool(store, zname)
        action(store, spec.name, seen.name, *args)

    await _off_loop(run)
    return await _written(request)


@router.put("/tools/{zname}/on", response_model=McpView)
async def tool_on(zname: str, request: Request) -> McpView:
    return await _tool_action(request, zname, manage.switch_tool, True)


@router.put("/tools/{zname}/off", response_model=McpView)
async def tool_off(zname: str, request: Request) -> McpView:
    return await _tool_action(request, zname, manage.switch_tool, False)


@router.put("/tools/{zname}/trust", response_model=McpView)
async def trust_tool(zname: str, request: Request) -> McpView:
    return await _tool_action(request, zname, manage.trust_tool)


@router.delete("/tools/{zname}/trust", response_model=McpView)
async def untrust_tool(zname: str, request: Request) -> McpView:
    return await _tool_action(request, zname, manage.untrust_tool)
