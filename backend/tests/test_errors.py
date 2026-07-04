from zygos.errors import (
    ConfigError,
    PluginError,
    ProviderAuthFailed,
    ProviderError,
    ProviderProtocolError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
    ZygosError,
)


def test_error_codes_are_stable():
    assert ZygosError.code == "zygos_error"
    assert ConfigError.code == "config_invalid"
    assert PluginError.code == "plugin_resolution_failed"


def test_specific_errors_are_zygos_errors():
    assert issubclass(ConfigError, ZygosError)
    assert issubclass(PluginError, ZygosError)


def test_provider_error_codes_and_retryability():
    cases = [
        (ProviderTimeout, "provider_timeout", True),
        (ProviderRateLimited, "provider_rate_limited", True),
        (ProviderAuthFailed, "provider_auth_failed", False),
        (ProviderUnavailable, "provider_unavailable", True),
        (ProviderProtocolError, "provider_protocol_error", False),
    ]
    for cls, code, retryable in cases:
        error = cls("boom", provider="ollama")
        assert isinstance(error, ProviderError)
        assert error.code == code
        assert error.retryable is retryable
        assert error.provider == "ollama"
