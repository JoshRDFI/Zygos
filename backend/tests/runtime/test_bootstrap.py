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
        "plugins:\n"
        "  providers:\n"
        "    ordered: 'collections:OrderedDict'\n",
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
