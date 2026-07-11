"""Unified error hierarchy (RFC-0001 §7). Stability: Experimental."""


class ZygosError(Exception):
    """Base for all runtime errors; carries a stable machine-readable code."""

    code: str = "zygos_error"


class ConfigError(ZygosError):
    code = "config_invalid"


class PluginError(ZygosError):
    code = "plugin_resolution_failed"


class ProviderError(ZygosError):
    """A model-provider call failed. `retryable` drives router fallback."""

    code = "provider_error"
    retryable: bool = False

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


class ProviderTimeout(ProviderError):
    code = "provider_timeout"
    retryable = True


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"
    retryable = True


class ProviderAuthFailed(ProviderError):
    code = "provider_auth_failed"
    retryable = False


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderProtocolError(ProviderError):
    code = "provider_protocol_error"
    retryable = False


class ToolError(ZygosError):
    """A tool operation failed. Base for the tool-error taxonomy.

    `retryable` drives the executor's retry loop (mirrors ProviderError.retryable).
    """

    code = "tool_error"
    retryable: bool = False


class ToolNotFound(ToolError):
    code = "tool_not_found"


class ToolTimeout(ToolError):
    code = "tool_timeout"
    retryable = True


class ToolPermissionDenied(ToolError):
    code = "tool_permission_denied"


class ToolTransient(ToolError):
    """A transient tool failure (e.g. a network transport fault). Retryable."""

    code = "tool_transient"
    retryable = True
