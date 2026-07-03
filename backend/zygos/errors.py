"""Unified error hierarchy (RFC-0001 §7)."""


class ZygosError(Exception):
    """Base for all runtime errors; carries a stable machine-readable code."""

    code: str = "zygos_error"


class ConfigError(ZygosError):
    code = "config_invalid"


class PluginError(ZygosError):
    code = "plugin_resolution_failed"
