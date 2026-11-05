"""resolve_default: the saved default or the config primary, with why (RFC-0013 §5)."""

from zygos.models.choices import DefaultModel, ModelChoices
from zygos.models.default import DefaultStatus, can_create, resolve_default
from zygos.services.router import RouteChoice

PRIMARY = RouteChoice("ollama", "qwen3:latest")


def _choices(provider: str, model: str) -> ModelChoices:
    return ModelChoices(default_model=DefaultModel(provider=provider, model=model))


def _resolve(choices, *, installed=None, routable=lambda p: True):
    return resolve_default(choices, PRIMARY, installed=lambda p: installed, routable=routable)


def test_none_saved_uses_config_primary():
    status = _resolve(ModelChoices())
    assert status == DefaultStatus(source="config", route=PRIMARY, ignored=None, reason=None)


def test_saved_and_installed_is_used():
    status = _resolve(_choices("ollama", "gemma4:e4b"), installed=frozenset({"gemma4:e4b"}))
    assert status.source == "saved"
    assert status.route == RouteChoice("ollama", "gemma4:e4b")
    assert status.ignored is None and status.reason is None


def test_saved_with_installed_unknown_is_trusted():
    status = _resolve(_choices("ollama", "gemma4:e4b"), installed=None)
    assert status.source == "saved"
    assert status.route == RouteChoice("ollama", "gemma4:e4b")


def test_saved_ollama_name_without_tag_matches_latest():
    status = _resolve(_choices("ollama", "gemma4"), installed=frozenset({"gemma4:latest"}))
    assert status.source == "saved"
    assert status.route == RouteChoice("ollama", "gemma4")


def test_saved_not_installed_is_ignored():
    saved = DefaultModel(provider="ollama", model="gone:7b")
    status = _resolve(ModelChoices(default_model=saved), installed=frozenset({"qwen3:latest"}))
    assert status == DefaultStatus(source="config", route=PRIMARY, ignored=saved, reason="not installed")


def test_saved_provider_unavailable_is_ignored():
    saved = DefaultModel(provider="anthropic", model="claude-x")
    status = _resolve(ModelChoices(default_model=saved), routable=lambda p: p != "anthropic")
    assert status == DefaultStatus(
        source="config", route=PRIMARY, ignored=saved, reason="anthropic isn't available")


def test_unavailable_wins_over_not_installed():
    saved = DefaultModel(provider="vllm", model="m")
    status = _resolve(ModelChoices(default_model=saved), installed=frozenset(),
                      routable=lambda p: False)
    assert status.reason == "vllm isn't available"


def test_status_serialises_route_as_provider_and_model():
    status = _resolve(_choices("ollama", "gemma4:e4b"))
    assert status.model_dump()["route"] == {"provider": "ollama", "model": "gemma4:e4b"}


def test_can_create():
    declared = {"ollama", "vllm", "anthropic", "openai", "fake"}
    assert can_create("ollama", declared=declared, api_key=None)
    assert can_create("vllm", declared=declared, api_key=None)
    assert not can_create("llamacpp", declared=declared | {"llamacpp"}, api_key=None)
    assert not can_create("anthropic", declared=declared, api_key=None)
    assert not can_create("openai", declared=declared, api_key="")
    assert can_create("openai", declared=declared, api_key="sk-x")
    assert not can_create("nope", declared=declared, api_key=None)
