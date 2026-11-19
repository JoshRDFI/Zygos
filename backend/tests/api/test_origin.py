import logging

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from zygos.api.app import create_app
from zygos.api.origin import origin_allowed
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


def _app(tmp_path, extra=""):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "providers:\n  primary:\n    provider: fake\n    model: demo\n"
        "tools:\n  enabled: []\n"
        f"personalization:\n  db_path: {tmp_path / 'prefs.db'}\n" + extra,
        encoding="utf-8",
    )
    return create_app(build_runtime(cfg))


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
