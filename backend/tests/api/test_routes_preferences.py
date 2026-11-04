import httpx
import pytest

from zygos.api.app import create_app
from zygos.runtime.bootstrap import build_runtime


def _app(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "providers:\n  primary:\n    provider: fake\n    model: demo\n"
        "tools:\n  enabled: []\n"
        f"personalization:\n  db_path: {tmp_path / 'prefs.db'}\n",
        encoding="utf-8",
    )
    return create_app(build_runtime(cfg))


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


_FIELDS = ("user_name", "address", "pronouns", "assistant_name", "tone", "persona")


@pytest.mark.asyncio
async def test_get_empty(tmp_path):
    async with _client(_app(tmp_path)) as c:
        resp = await c.get("/preferences")
    assert resp.status_code == 200
    assert resp.json() == {f: None for f in _FIELDS}


@pytest.mark.asyncio
async def test_put_then_get_round_trip(tmp_path):
    body = {"user_name": "Josh", "address": None, "pronouns": "he/him", "assistant_name": "Zee", "tone": None, "persona": "dry"}
    async with _client(_app(tmp_path)) as c:
        put = await c.put("/preferences", json=body)
        got = await c.get("/preferences")
    assert put.status_code == 200
    assert put.json() == body
    assert got.json() == body


@pytest.mark.asyncio
async def test_put_invalid_is_422_and_not_written(tmp_path):
    async with _client(_app(tmp_path)) as c:
        resp = await c.put("/preferences", json={"user_name": "x" * 65})
        got = await c.get("/preferences")
    assert resp.status_code == 422
    assert got.json()["user_name"] is None


@pytest.mark.asyncio
async def test_put_is_seen_by_turn_deps(tmp_path):
    app = _app(tmp_path)
    async with _client(app) as c:
        await c.put("/preferences", json={"user_name": "Josh"})
    assert app.state.turn_deps.preferences.get().user_name == "Josh"
