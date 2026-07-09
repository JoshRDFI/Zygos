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
