from zygos.errors import ConfigError, PluginError, ZygosError


def test_error_codes_are_stable():
    assert ZygosError.code == "zygos_error"
    assert ConfigError.code == "config_invalid"
    assert PluginError.code == "plugin_resolution_failed"


def test_specific_errors_are_zygos_errors():
    assert issubclass(ConfigError, ZygosError)
    assert issubclass(PluginError, ZygosError)
