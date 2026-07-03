from zygos.config.env import resolve_env_placeholders


def test_placeholder_resolves_from_environment(monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    assert resolve_env_placeholders("${ZYGOS_TEST_KEY}") == "sekrit"


def test_missing_placeholder_resolves_to_none(monkeypatch):
    monkeypatch.delenv("ZYGOS_TEST_KEY", raising=False)
    assert resolve_env_placeholders("${ZYGOS_TEST_KEY}") is None


def test_non_placeholder_strings_and_scalars_pass_through():
    assert resolve_env_placeholders("plain") == "plain"
    assert resolve_env_placeholders("prefix ${NOT_WHOLE}") == "prefix ${NOT_WHOLE}"
    assert resolve_env_placeholders(42) == 42


def test_recurses_into_dicts_and_lists(monkeypatch):
    monkeypatch.setenv("ZYGOS_TEST_KEY", "sekrit")
    value = {"credentials": {"openai": {"api_key": "${ZYGOS_TEST_KEY}"}}, "routes": ["${ZYGOS_TEST_KEY}"]}
    resolved = resolve_env_placeholders(value)
    assert resolved["credentials"]["openai"]["api_key"] == "sekrit"
    assert resolved["routes"] == ["sekrit"]
