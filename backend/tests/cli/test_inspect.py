import asyncio

from zygos.cli.__main__ import main, render_manifest
from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.manifest import runtime_manifest


def test_render_manifest_includes_capabilities_and_routes():
    runtime = build_runtime()  # default ollama config, no key needed
    try:
        text = render_manifest(runtime_manifest(runtime))
    finally:
        asyncio.run(runtime.aclose())
    assert "local_inference: ollama" in text
    assert "primary route: ollama:qwen3:8b" in text


def test_inspect_command_exits_zero(capsys):
    code = main(["inspect"])
    assert code == 0
    out = capsys.readouterr().out
    assert "capabilities:" in out


def test_inspect_survives_unroutable_model(monkeypatch, capsys):
    """I2: `zygos inspect` must not crash when every circuit is open."""
    from dataclasses import replace

    import zygos.cli.__main__ as cli
    from zygos.errors import ProviderUnavailable
    from zygos.providers.fake import FakeProvider
    from zygos.thinking.support import ThinkingSupportChecker

    class _Unroutable:
        def select_model(self, *a, **k):
            raise ProviderUnavailable("No eligible provider routes", provider="router")

    real = cli.build_runtime

    def fake_build(*a, **k):
        rt = real(*a, **k)
        return replace(rt, model_service=_Unroutable(), thinking_support=ThinkingSupportChecker(
            {rt.config.providers.primary.provider: FakeProvider(think_capable=True)}))

    monkeypatch.setattr(cli, "build_runtime", fake_build)
    code = main(["inspect"])
    assert code == 0
    assert "capabilities:" in capsys.readouterr().out
