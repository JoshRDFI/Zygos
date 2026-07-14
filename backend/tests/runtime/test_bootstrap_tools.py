import pytest

from zygos.errors import PluginError
from zygos.runtime.bootstrap import build_runtime
from zygos.tools.permissions import AllowingResolver


def test_default_config_builds_four_tools():
    rt = build_runtime()
    names = {t.meta.name for t in rt.tools}
    assert names == {"read_file", "write_file", "http_fetch", "run_command"}
    assert rt.tool_loop_config.max_iterations == 8


def test_default_policy_loosens_http_fetch():
    rt = build_runtime()
    http = next(t for t in rt.tools if t.meta.name == "http_fetch")
    assert rt.tool_service._policy.decide(http.meta) == "allow"
    run = next(t for t in rt.tools if t.meta.name == "run_command")
    assert rt.tool_service._policy.decide(run.meta) == "ask"


def test_bind_resolver_swaps_resolver():
    rt = build_runtime()
    resolver = AllowingResolver()
    rt.tool_service.bind_resolver(resolver)
    assert rt.tool_service._resolver is resolver


def test_disabled_tools_yield_empty(tmp_path, monkeypatch):
    from zygos.config import loader as loader_mod
    from zygos.config.schema import ToolsConfig, ZygosConfig
    base = ZygosConfig()
    monkeypatch.setattr(loader_mod, "load_config",
                        lambda p=None: base.model_copy(update={"tools": ToolsConfig(enabled=[])}))
    # build_runtime imports load_config by name; patch there too:
    import zygos.runtime.bootstrap as bs
    monkeypatch.setattr(bs, "load_config",
                        lambda p=None: base.model_copy(update={"tools": ToolsConfig(enabled=[])}))
    rt = build_runtime()
    assert rt.tools == ()


def test_undeclared_tool_name_raises(monkeypatch):
    import zygos.runtime.bootstrap as bs
    from zygos.config.schema import ToolsConfig, ZygosConfig
    base = ZygosConfig()
    monkeypatch.setattr(bs, "load_config",
                        lambda p=None: base.model_copy(update={"tools": ToolsConfig(enabled=["nope"])}))
    with pytest.raises(PluginError):
        build_runtime()
