from fastapi import FastAPI

from zygos.cli.__main__ import _build_parser
from zygos.api.app import run_server
from zygos.runtime.bootstrap import build_runtime


def test_parser_accepts_serve_with_overrides():
    args = _build_parser().parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.command == "serve"
    assert args.host == "0.0.0.0"
    assert args.port == 9000


def test_run_server_wires_app_and_invokes_run():
    runtime = build_runtime()
    captured = {}

    def fake_run(app, *, host, port):
        captured["app"] = app
        captured["host"] = host
        captured["port"] = port

    try:
        run_server(runtime, host="127.0.0.1", port=1234, run=fake_run)
    finally:
        import asyncio
        asyncio.run(runtime.aclose())

    assert isinstance(captured["app"], FastAPI)
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 1234
    # serve wires no live embedder (LocalEmbedder loads eagerly)
    assert captured["app"].state.embedder is None


def test_run_server_allows_the_bind_host_in_host_header():
    from starlette.testclient import TestClient

    runtime = build_runtime()
    captured = {}

    try:
        run_server(runtime, host="192.168.1.20", port=8000,
                   run=lambda app, *, host, port: captured.update(app=app))
        with TestClient(captured["app"]) as c:
            ok = c.get("/preferences", headers={"Host": "192.168.1.20:8000"})
            bad = c.get("/preferences", headers={"Host": "evil.example:8000"})
    finally:
        import asyncio
        asyncio.run(runtime.aclose())

    assert ok.status_code != 403
    assert bad.status_code == 403
