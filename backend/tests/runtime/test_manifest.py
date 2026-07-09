import asyncio

from zygos.runtime.bootstrap import build_runtime
from zygos.runtime.capabilities import Capability
from zygos.runtime.manifest import Manifest, runtime_manifest


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
