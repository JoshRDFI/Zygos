from pathlib import Path

import pytest

from zygos.api.app import create_app
from zygos.api.permission import WebSocketPromptResolver
from zygos.runtime.bootstrap import build_runtime


def test_create_app_binds_resolver_and_fills_turn_deps():
    rt = build_runtime()
    app = create_app(rt)
    assert isinstance(rt.tool_service._resolver, WebSocketPromptResolver)
    deps = app.state.turn_deps
    assert deps.tool_service is rt.tool_service
    assert {t.meta.name for t in deps.tools} == {"read_file", "write_file", "http_fetch", "run_command"}
    assert deps.tool_loop_config is rt.tool_loop_config


@pytest.mark.asyncio
async def test_lifespan_creates_workspace(tmp_path, monkeypatch):
    import zygos.runtime.bootstrap as bs
    from zygos.config.schema import ToolsConfig, ZygosConfig
    ws = tmp_path / "ws"
    base = ZygosConfig()
    monkeypatch.setattr(bs, "load_config",
                        lambda p=None: base.model_copy(update={"tools": ToolsConfig(workspace_root=str(ws))}))
    rt = build_runtime()
    app = create_app(rt)
    async with app.router.lifespan_context(app):
        assert Path(ws).is_dir()
