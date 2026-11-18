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


async def test_manifest_thinking_from_cache():
    from dataclasses import replace

    from zygos.providers.fake import FakeProvider
    from zygos.thinking.support import ThinkingSupportChecker

    runtime = build_runtime()
    try:
        route = runtime.model_service.select_model()
        assert runtime_manifest(runtime).thinking is None
        runtime = replace(runtime, thinking_support=ThinkingSupportChecker(
            {route.provider: FakeProvider(think_capable=True)}))
        result = await runtime.thinking_support.check(route)
        assert result.supported is True
        assert runtime_manifest(runtime).thinking == result
    finally:
        await runtime.aclose()


def test_manifest_secrets_entry_has_no_location_or_values(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{tmp_path / '.zygos' / 'p.db'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
        "secrets:\n  backend: encrypted_file\n"
    )
    runtime = build_runtime(cfg)
    try:
        manifest = runtime_manifest(runtime)
    finally:
        asyncio.run(runtime.aclose())
    s = manifest.secrets
    assert s is not None
    assert set(type(s).model_fields) == {"backend", "reason", "available"}
    assert s.backend == "encrypted_file"
    assert str(tmp_path) not in manifest.model_dump_json()


def test_manifest_survives_keyring_discovery_error(tmp_path, monkeypatch):
    import pytest

    keyring = pytest.importorskip("keyring")

    def boom():
        raise ModuleNotFoundError("nonexistent.mod")

    monkeypatch.setattr(keyring, "get_keyring", boom)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"personalization:\n  db_path: '{tmp_path / '.zygos' / 'p.db'}'\n"
        "providers:\n  primary: {provider: fake, model: fake-1}\n"
    )
    runtime = build_runtime(cfg)
    try:
        manifest = runtime_manifest(runtime)
    finally:
        asyncio.run(runtime.aclose())
    assert manifest.secrets is not None


def test_manifest_accepts_a_precomputed_secrets_status(tmp_path):
    from zygos.secrets.resolve import SecretsStatus

    runtime = build_runtime()
    calls = []
    runtime.secrets.status = lambda: calls.append(1)  # must not be called
    status = SecretsStatus("keyring", "set in config", False, "why", None)
    try:
        manifest = runtime_manifest(runtime, secrets_status=status)
    finally:
        asyncio.run(runtime.aclose())
    assert calls == []
    assert (manifest.secrets.backend, manifest.secrets.available) == ("keyring", False)
