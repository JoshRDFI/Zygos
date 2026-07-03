"""Config-declared plugin resolution (RFC-0001 §3).

Plugins are declared in config as ``kind -> name -> "module.path:ClassName"``.
Reading the config tells you exactly what code runs; nothing auto-activates.
"""

import importlib

from zygos.errors import PluginError


def resolve_class(path: str) -> type:
    module_path, _, attribute = path.partition(":")
    if not module_path or not attribute:
        raise PluginError(
            f"Invalid plugin path {path!r}: expected 'module.path:ClassName'."
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as error:
        raise PluginError(f"Cannot import plugin module {module_path!r}: {error}") from error
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise PluginError(
            f"Module {module_path!r} has no attribute {attribute!r}."
        ) from error


class PluginRegistry:
    def __init__(self, declarations: dict[str, dict[str, str]]) -> None:
        self._declarations = declarations

    def resolve(self, kind: str, name: str) -> type:
        path = self._declarations.get(kind, {}).get(name)
        if path is None:
            raise PluginError(f"No plugin declared for {kind}/{name}.")
        return resolve_class(path)

    def list(self, kind: str) -> list[str]:
        return sorted(self._declarations.get(kind, {}))
