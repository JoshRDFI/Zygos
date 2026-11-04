"""One address resolution for Ollama and vLLM (RFC-0014 section 2)."""

from zygos.backends.addresses import BACKEND_ADDRESSES, resolve_address, restart_required, routed
from zygos.backends.settings import BackendsSettings, OllamaBackend, VllmEndpoint
from zygos.config.schema import ZygosConfig


def _config(**providers) -> ZygosConfig:
    return ZygosConfig.model_validate({"providers": providers})


CFG = _config(
    primary={"provider": "fake", "model": "f"},
    credentials={"ollama": {"base_url": "http://cfg:1"}, "vllm": {"base_url": "http://cfgv:2/v1"}},
)


def test_record_then_config_then_default():
    record = BackendsSettings(ollama=OllamaBackend(base_url="http://rec:2"),
                              vllm=[VllmEndpoint(base_url="http://v:3/v1")])
    assert resolve_address(CFG, "ollama", record) == ("http://rec:2", "backends")
    assert resolve_address(CFG, "vllm", record) == ("http://v:3/v1", "backends")
    assert resolve_address(CFG, "ollama", BackendsSettings()) == ("http://cfg:1", "config")
    assert resolve_address(CFG, "vllm", None) == ("http://cfgv:2/v1", "config")
    assert resolve_address(ZygosConfig(), "ollama", None) == ("http://localhost:11434", "default")
    assert resolve_address(ZygosConfig(), "vllm", None) == ("http://localhost:8000/v1", "default")
    assert BACKEND_ADDRESSES == ("ollama", "vllm")


def test_routed_lists_primary_and_fallback_providers():
    config = _config(primary={"provider": "ollama", "model": "a"},
                     fallbacks=[{"provider": "vllm", "model": "b"}])
    assert routed(config) == {"ollama", "vllm"}
    assert routed(CFG) == {"fake"}


def test_restart_required_when_resolved_address_differs_from_start():
    start = {"ollama": "http://rec:2", "vllm": "http://cfgv:2/v1"}
    recorded = BackendsSettings(ollama=OllamaBackend(base_url="http://rec:2"))
    assert restart_required(recorded, CFG, start) is False
    # clearing the recorded address falls back to the config credential: a change
    assert restart_required(BackendsSettings(), CFG, start) is True
    # a trailing slash is the same address
    assert restart_required(BackendsSettings(ollama=OllamaBackend(base_url="http://rec:2/")),
                            CFG, start) is False
    # vLLM newly recorded
    assert restart_required(
        BackendsSettings(ollama=OllamaBackend(base_url="http://rec:2"),
                         vllm=[VllmEndpoint(base_url="http://new:9/v1")]), CFG, start) is True
