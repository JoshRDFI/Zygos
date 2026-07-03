import pytest

from zygos.errors import PluginError
from zygos.plugins.resolver import PluginRegistry, resolve_class


def test_resolve_class_loads_a_real_class():
    cls = resolve_class("collections:OrderedDict")
    from collections import OrderedDict

    assert cls is OrderedDict


def test_resolve_class_rejects_malformed_path():
    with pytest.raises(PluginError, match="module.path:ClassName"):
        resolve_class("no-colon-here")


def test_resolve_class_rejects_missing_module():
    with pytest.raises(PluginError, match="zygos_no_such_module"):
        resolve_class("zygos_no_such_module:Thing")


def test_resolve_class_rejects_missing_attribute():
    with pytest.raises(PluginError, match="NoSuchClass"):
        resolve_class("collections:NoSuchClass")


def test_registry_resolves_declared_plugins():
    registry = PluginRegistry({"providers": {"ordered": "collections:OrderedDict"}})
    from collections import OrderedDict

    assert registry.resolve("providers", "ordered") is OrderedDict
    assert registry.list("providers") == ["ordered"]
    assert registry.list("voices") == []


def test_registry_rejects_unknown_plugin():
    registry = PluginRegistry({})
    with pytest.raises(PluginError, match="providers/unknown"):
        registry.resolve("providers", "unknown")
