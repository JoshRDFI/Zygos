import asyncio

from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.capabilities import Capability
from zygos.runtime.manifest import Manifest, _scrub_error, runtime_manifest


def test_manifest_lists_the_local_inference_binding():
    runtime = build_runtime()  # default ollama primary
    try:
        manifest = runtime_manifest(runtime)
    finally:
        asyncio.run(runtime.aclose())

    assert isinstance(manifest, Manifest)
    assert Capability.LOCAL_INFERENCE in manifest.capabilities
    providers = [b.provider for b in manifest.capabilities[Capability.LOCAL_INFERENCE]]
    assert providers == ["ollama"]
    assert manifest.primary_route.provider == "ollama"
    assert manifest.lifecycle_stage == "register_capabilities"


def test_manifest_contains_no_secret_material(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(
        "providers:\n"
        "  primary: {provider: openai, model: gpt-4o}\n"
        "  credentials:\n"
        "    openai: {api_key: SECRET-KEY-123}\n"
    )
    runtime = build_runtime(config)
    try:
        dumped = runtime_manifest(runtime).model_dump_json()
    finally:
        asyncio.run(runtime.aclose())

    assert "SECRET-KEY-123" not in dumped


def test_scrub_error_redacts_posix_path():
    out = _scrub_error("failed to load /home/sage/.zygos/models/base.en: bad magic")
    assert "/home/sage" not in out
    assert "<path>" in out
    assert "bad magic" in out   # error class/detail preserved


def test_scrub_error_redacts_windows_path():
    out = _scrub_error(r"cannot open C:\Users\sage\models\ggml.bin")
    assert r"C:\Users" not in out
    assert "<path>" in out


def test_scrub_error_passthrough_none_and_plain():
    assert _scrub_error(None) is None
    assert _scrub_error("connection refused") == "connection refused"


def test_scrub_error_truncates():
    assert len(_scrub_error("x" * 500)) <= 200


def test_scrub_error_keeps_non_path_slashes():
    assert _scrub_error("retry and/or fail, ratio 1/2") == "retry and/or fail, ratio 1/2"
