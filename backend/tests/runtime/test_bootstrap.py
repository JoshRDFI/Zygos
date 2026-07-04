import dataclasses
from pathlib import Path

from zygos.plugins.resolver import PluginRegistry
from zygos.runtime.bootstrap import RuntimeAssembly, build_runtime


def test_build_runtime_with_defaults():
    assembly = build_runtime()
    assert assembly.config.providers.primary.provider == "ollama"
    assert isinstance(assembly.plugins, PluginRegistry)


def test_build_runtime_wires_declared_plugins(tmp_path: Path):
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: fake\n"
        "    model: demo\n"
        "plugins:\n"
        "  providers:\n"
        "    ordered: 'collections:OrderedDict'\n"
        "    fake: 'zygos.providers.fake:FakeProvider'\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    from collections import OrderedDict

    assert assembly.plugins.resolve("providers", "ordered") is OrderedDict


def test_assembly_is_immutable():
    assembly = build_runtime()
    try:
        assembly.config = None  # type: ignore[misc]
        raised = False
    except dataclasses.FrozenInstanceError:
        raised = True
    assert raised, "RuntimeAssembly must be a frozen dataclass"


from zygos.providers.types import GenerationRequest, Message
from zygos.services.model import DefaultModelService


async def test_default_runtime_exposes_model_service():
    assembly = build_runtime()
    try:
        assert isinstance(assembly.model_service, DefaultModelService)
        choice = assembly.model_service.select_model()
        assert (choice.provider, choice.model) == ("ollama", "qwen3:8b")
    finally:
        await assembly.aclose()


async def test_swap_primary_to_fake_via_config_alone(tmp_path: Path):
    """RFC-0001 acceptance criterion 3: provider swap with zero code changes."""
    file = tmp_path / "config.yaml"
    file.write_text(
        "providers:\n"
        "  primary:\n"
        "    provider: fake\n"
        "    model: demo\n",
        encoding="utf-8",
    )
    assembly = build_runtime(file)
    try:
        request = GenerationRequest(messages=(Message(role="user", content="ping"),))
        result = await assembly.model_service.generate(request)
        assert result.provider == "fake"
        assert result.model == "demo"
        assert result.text  # non-empty, produced with zero network and zero keys
    finally:
        await assembly.aclose()
