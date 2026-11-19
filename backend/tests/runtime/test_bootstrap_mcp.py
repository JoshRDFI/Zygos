"""The MCP supervisor in the runtime: always built, gate bound, closed first, SDK never
imported while no server is stored."""

from __future__ import annotations

import dataclasses
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from zygos.mcp.supervisor import McpSupervisor
from zygos.runtime.bootstrap import build_runtime

BACKEND = Path(__file__).resolve().parents[2]


def _config(tmp_path: Path) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{tmp_path / '.zygos' / 'p.db'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    return cfg


async def test_runtime_builds_supervisor_and_binds_gate(tmp_path):
    runtime = build_runtime(_config(tmp_path))
    try:
        assert isinstance(runtime.mcp, McpSupervisor)
        assert runtime.tool_service._mcp_gate == runtime.mcp.gate
        assert runtime.mcp.before_turn() == ()
        assert not (tmp_path / ".zygos" / "p.db").exists()  # no servers: nothing written
    finally:
        await runtime.aclose()


async def test_aclose_closes_mcp_before_http_client(tmp_path):
    runtime = build_runtime(_config(tmp_path))
    seen: list[bool] = []

    real = runtime.mcp

    class Recording:
        async def aclose(self) -> None:
            seen.append(runtime.http_client.is_closed)
            await real.aclose()

    runtime = dataclasses.replace(runtime, mcp=Recording())
    await runtime.aclose()
    assert seen == [False]
    assert runtime.http_client.is_closed
    assert real._closed


async def test_aclose_continues_when_mcp_close_fails(tmp_path, caplog):
    runtime = build_runtime(_config(tmp_path))
    real = runtime.mcp

    class Failing:
        async def aclose(self) -> None:
            await real.aclose()
            raise RuntimeError("close boom")

    runtime = dataclasses.replace(runtime, mcp=Failing())
    await runtime.aclose()
    assert runtime.http_client.is_closed
    assert "RuntimeError" in caplog.text and "close boom" not in caplog.text


_NO_SERVER_RUN = textwrap.dedent(
    """
    import asyncio, sys
    from pathlib import Path
    from zygos.api.app import create_app
    from zygos.api.session import Session
    from zygos.api.turn import run_turn
    from zygos.runtime.bootstrap import build_runtime
    from zygos.runtime.context import CancelToken
    from zygos.runtime.manifest import runtime_manifest

    assert "mcp" not in sys.modules, "imported before the run"

    async def main():
        runtime = build_runtime(Path(sys.argv[1]))
        app = create_app(runtime)
        async with app.router.lifespan_context(app):
            runtime = app.state.runtime
            session = Session("s1", runtime.new_context(session_id="s1"), created_at=0.0)
            await run_turn(session, app.state.turn_deps, "hello", CancelToken(),
                           spoken_input=False, think=None)
            frames = []
            while not session.outbound.empty():
                frames.append(session.outbound.get_nowait())
            assert frames[-1].type == "turn.end", frames
            assert runtime_manifest(runtime).mcp_servers == ()

    asyncio.run(main())
    loaded = sorted(m for m in sys.modules if m == "mcp" or m.startswith(("mcp.", "mcp_")))
    print("LOADED", loaded)
    assert not loaded, loaded
    """
)


def test_mcp_never_imported_with_no_servers(tmp_path):
    """Ruling 4: in a fresh interpreter (other tests in this process import the SDK)."""
    cfg = _config(tmp_path)
    env = {**os.environ, "ZYGOS_HOME": str(tmp_path / "home")}
    proc = subprocess.run(
        [sys.executable, "-c", _NO_SERVER_RUN, str(cfg)],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "LOADED []" in proc.stdout
