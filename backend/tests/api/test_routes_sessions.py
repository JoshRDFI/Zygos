from fastapi import FastAPI
from fastapi.testclient import TestClient

from zygos.api.routes_sessions import router
from zygos.api.session import SessionRegistry
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus


def _client():
    app = FastAPI()
    bus = InProcessEventBus()
    n = {"i": 0}

    def new_id():
        n["i"] += 1
        return f"sess-{n['i']}"

    app.state.registry = SessionRegistry(
        new_context=lambda sid: root_context(bus, session_id=sid),
        clock=lambda: 12.0, new_id=new_id,
    )
    app.include_router(router)
    return TestClient(app)


def test_post_creates_session():
    client = _client()
    r = client.post("/sessions")
    assert r.status_code == 200
    assert r.json() == {"id": "sess-1"}


def test_get_lists_and_gets_snapshot():
    client = _client()
    sid = client.post("/sessions").json()["id"]
    listing = client.get("/sessions").json()
    assert [s["id"] for s in listing] == [sid]
    one = client.get(f"/sessions/{sid}").json()
    assert one["id"] == sid and one["turn_status"] == "idle" and one["connected"] is False


def test_get_unknown_is_404():
    assert _client().get("/sessions/nope").status_code == 404


def test_delete_removes_then_404():
    client = _client()
    sid = client.post("/sessions").json()["id"]
    assert client.delete(f"/sessions/{sid}").json() == {"deleted": sid}
    assert client.delete(f"/sessions/{sid}").status_code == 404
