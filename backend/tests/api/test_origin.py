import asyncio
import logging

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zygos.api.app import create_app
from zygos.api.origin import allowed_hosts_for, host_allowed, origin_allowed
from zygos.api.origin import OriginGuard
from zygos.config.schema import ServerConfig
from zygos.runtime.bootstrap import build_runtime


@pytest.mark.parametrize(
    ("origin", "extra", "expected"),
    [
        (None, [], True),
        ("http://localhost:5173", [], True),
        ("http://127.0.0.1:5174", [], True),
        ("http://[::1]:8000", [], True),
        ("http://localhost", [], True),
        ("https://zygos.example", ["https://zygos.example/"], True),
        ("https://evil.example", [], False),
        ("http://localhost.evil.example", [], False),
        ("http://127.0.0.1.evil.example:80", [], False),
        ("null", [], False),
        ("not a url", [], False),
        ("ftp://localhost", [], False),
        ("http://localhost:notaport", [], False),
    ],
)
def test_origin_allowed(origin, extra, expected):
    assert origin_allowed(origin, extra) is expected


def _cfg_path(tmp_path, extra=""):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "providers:\n  primary:\n    provider: fake\n    model: demo\n"
        "tools:\n  enabled: []\n"
        f"personalization:\n  db_path: {tmp_path / 'prefs.db'}\n" + extra,
        encoding="utf-8",
    )
    return cfg


def _app(tmp_path, extra=""):
    return create_app(build_runtime(_cfg_path(tmp_path, extra)))


_BODY = {"user_name": "Josh"}
_EVIL = {"Origin": "https://evil.example"}


def test_put_preferences_refused_from_other_origin(tmp_path, caplog):
    with TestClient(_app(tmp_path)) as c, caplog.at_level(logging.WARNING):
        r = c.put("/preferences", json=_BODY, headers=_EVIL)
        got = c.get("/preferences").json()
    assert r.status_code == 403
    assert r.json() == {"detail": "origin not allowed"}
    assert got["user_name"] is None
    assert "https://evil.example" in caplog.text


def test_put_preferences_allowed_without_origin(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        assert c.put("/preferences", json=_BODY).status_code == 200


def test_put_preferences_allowed_from_vite_origin(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        r = c.put("/preferences", json=_BODY, headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200


def test_put_allowed_from_configured_origin(tmp_path):
    app = _app(tmp_path, "server:\n  allowed_origins: ['https://zygos.example/']\n")
    with TestClient(app) as c:
        r = c.put("/preferences", json=_BODY, headers={"Origin": "https://zygos.example"})
    assert r.status_code == 200


def test_get_not_checked(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        assert c.get("/preferences", headers=_EVIL).status_code == 200


def test_ws_refused_from_other_origin_4403(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        sid = c.post("/sessions").json()["id"]
        with c.websocket_connect(f"/ws/session/{sid}", headers=_EVIL) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
    assert exc.value.code == 4403


def test_ws_refused_before_session_lookup(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        with c.websocket_connect("/ws/session/nope", headers=_EVIL) as ws:
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_text()
    assert exc.value.code == 4403


def test_ws_allowed_from_vite_origin(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        sid = c.post("/sessions").json()["id"]
        with c.websocket_connect(
            f"/ws/session/{sid}", headers={"Origin": "http://localhost:5173"}
        ) as ws:
            ws.send_text('{"channel":"control","type":"ping","payload":{}}')
            assert ws.receive_text()


_LOCAL = frozenset({"localhost", "127.0.0.1", "::1"})


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        (None, True),
        ("localhost", True),
        ("localhost:8000", True),
        ("127.0.0.1", True),
        ("127.0.0.1:8000", True),
        ("[::1]:8000", True),
        ("[::1]", True),
        ("LocalHost:8000", True),
        ("localhost.", True),
        ("localhost.:8000", True),
        ("evil.example", False),
        ("evil.example:8000", False),
        ("localhost.evil.example", False),
        ("127.0.0.1.evil.example", False),
        ("127.0.0.1.evil.example:8000", False),
        ("[::1", False),
        ("host:notaport", False),
        ("localhost:notaport", False),
        ("", False),
        ("localhost:8000:9", False),
        ("localhost evil.example", False),
    ],
)
def test_host_allowed(host, expected):
    assert host_allowed(host, _LOCAL) is expected


def test_host_allowed_ignores_port_and_case_for_configured_host():
    allowed = frozenset({"zygos.example"})
    assert host_allowed("Zygos.Example:8443", allowed) is True
    assert host_allowed("zygos.example.", allowed) is True
    assert host_allowed("localhost", allowed) is False


def _server(**kw):
    return ServerConfig(**kw)


def test_allowed_hosts_for_default_is_loopback_only():
    assert allowed_hosts_for(_server()) == _LOCAL


def test_allowed_hosts_for_takes_hostnames_from_allowed_origins():
    got = allowed_hosts_for(_server(allowed_origins=["https://Zygos.Example:8443/", "http://10.0.0.5"]))
    assert {"zygos.example", "10.0.0.5"} <= got


def test_allowed_hosts_for_specific_bind_address_only():
    assert "192.168.1.20" in allowed_hosts_for(_server(host="192.168.1.20"))
    for wildcard in ("0.0.0.0", "::", ""):
        assert allowed_hosts_for(_server(host=wildcard)) == _LOCAL


def test_allowed_hosts_for_includes_configured_entries():
    got = allowed_hosts_for(_server(allowed_hosts=["Zygos.lan", "192.168.1.20"]))
    assert {"zygos.lan", "192.168.1.20"} <= got


_REBIND = {"Host": "evil.example:8000"}
_HOST_MSG = {"detail": "host not allowed; add it to server.allowed_hosts"}


def test_get_refused_for_foreign_host(tmp_path, caplog):
    with TestClient(_app(tmp_path)) as c, caplog.at_level(logging.WARNING):
        r = c.get("/preferences", headers=_REBIND)
    assert r.status_code == 403
    assert r.json() == _HOST_MSG
    assert "evil.example:8000" in caplog.text


def test_session_history_refused_for_foreign_host(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        r = c.get("/sessions", headers=_REBIND)
    assert r.status_code == 403


def test_get_allowed_for_localhost_host(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        r = c.get("/preferences", headers={"Host": "localhost:8000"})
    assert r.status_code == 200


def test_foreign_host_refused_on_write_too(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        r = c.put("/preferences", json=_BODY, headers=_REBIND)
    assert r.status_code == 403
    assert r.json() == _HOST_MSG


def test_websocket_refused_for_foreign_host(tmp_path):
    with TestClient(_app(tmp_path)) as c:
        with pytest.raises(WebSocketDisconnect) as exc:
            # s1 does not exist: without the Host guard this would close 4404, not 4403
            with c.websocket_connect("/ws/session/s1", headers=_REBIND):
                pass
    assert exc.value.code == 4403


def test_configured_allowed_hosts_entry_is_allowed(tmp_path):
    app = _app(tmp_path, "server:\n  allowed_hosts: [zygos.lan]\n")
    with TestClient(app) as c:
        ok = c.get("/preferences", headers={"Host": "zygos.lan:8000"})
        bad = c.get("/preferences", headers=_REBIND)
    assert ok.status_code == 200
    assert bad.status_code == 403


def test_bind_host_argument_is_allowed(tmp_path):
    app = create_app(build_runtime(_cfg_path(tmp_path)), bind_host="192.168.1.20")
    with TestClient(app) as c:
        ok = c.get("/preferences", headers={"Host": "192.168.1.20:8000"})
        bad = c.get("/preferences", headers=_REBIND)
    assert ok.status_code == 200
    assert bad.status_code == 403


def test_bind_host_wildcard_adds_nothing():
    for wildcard in ("0.0.0.0", "::"):
        assert allowed_hosts_for(_server(), wildcard) == _LOCAL


def test_bind_host_overrides_configured_host():
    got = allowed_hosts_for(_server(host="10.0.0.1"), "10.0.0.2")
    assert "10.0.0.2" in got
    assert "10.0.0.1" not in got


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        ("[fe80::1]", "fe80::1"),
        ("fe80::1", "fe80::1"),
        ("zygos.lan:8443", "zygos.lan"),
        ("http://zygos.lan", "zygos.lan"),
        ("https://Zygos.LAN:8443/", "zygos.lan"),
        ("http://[fe80::1]:8000", "fe80::1"),
        (" Zygos.lan. ", "zygos.lan"),
    ],
)
def test_allowed_hosts_entries_are_normalised(entry, expected):
    assert expected in allowed_hosts_for(_server(allowed_hosts=[entry]))
    assert host_allowed(f"{'[' + expected + ']' if ':' in expected else expected}:8000",
                        allowed_hosts_for(_server(allowed_hosts=[entry])))


def test_bracketed_server_host_is_normalised():
    assert "fe80::1" in allowed_hosts_for(_server(host="[fe80::1]"))


@pytest.mark.parametrize("entry", ["", "a b", "host:notaport", "http://user@zygos.lan", "zygos.lan/path", "[::1"])
def test_unparseable_allowed_hosts_entry_is_rejected(entry):
    with pytest.raises(ValidationError, match="allowed_hosts"):
        ServerConfig(allowed_hosts=[entry])


def test_request_without_host_header_reaches_inner_app():
    reached = []

    async def inner(scope, receive, send):
        reached.append(scope["type"])

    guard = OriginGuard(inner, allowed_hosts=_LOCAL)
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [(b"accept", b"*/*")]}
    asyncio.run(guard(scope, None, None))
    assert reached == ["http"]
