"""ModelCatalog: the GET /models view (RFC-0013 §1-§3, §11)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from zygos.config.schema import ZygosConfig
from zygos.errors import ProviderUnavailable
from zygos.hardware.probe import HardwareProbe
from zygos.models.catalog import ModelCatalog
from zygos.models.fit import KOKORO_CUDA_RESERVE_BYTES
from zygos.models.store import ProfileStore
from zygos.providers.types import OllamaModel, OllamaRunning, OllamaShow
from zygos.runtime.capabilities import Capability
from zygos.runtime.context import root_context
from zygos.runtime.events import InProcessEventBus
from zygos.voice.contract import TtsHealth
from zygos.voice.service import VoiceState

GiB = 1024**3
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

QWEN_INFO = {
    "general.architecture": "qwen3",
    "general.parameter_count": 8_000_000_000,
    "qwen3.block_count": 36,
    "qwen3.attention.head_count_kv": 8,
    "qwen3.attention.key_length": 128,
    "qwen3.context_length": 40960,
}


def _tag(name, digest, size=5 * GiB, family="qwen3"):
    return OllamaModel(name=name, size=size, digest=digest, family=family,
                       parameter_size="8.2B", quantization_level="Q4_K_M")


class FakeOllama:
    name = "ollama"
    capabilities = frozenset({Capability.LOCAL_INFERENCE})

    def __init__(self, tags=(), running=(), *, fail=None, show_fail=False):
        self.tags = tuple(tags)
        self.running = tuple(running)
        self.fail = fail
        self.show_fail = show_fail
        self.show_calls: list[str] = []

    async def list_models(self):
        if self.fail is not None:
            raise self.fail
        return self.tags

    async def running_models(self):
        if self.fail is not None:
            raise self.fail
        return self.running

    async def show(self, model):
        self.show_calls.append(model)
        if self.show_fail:
            raise ProviderUnavailable("show timed out", provider="ollama")
        return OllamaShow(capabilities=("completion", "tools", "thinking"), model_info=QWEN_INFO,
                          parameters="num_ctx 8192")


class FakeCloud:
    name = "anthropic"
    capabilities = frozenset({Capability.LOCAL_INFERENCE})  # every generator declares it


class FakeVllm:
    name = "vllm"
    capabilities = frozenset({Capability.LOCAL_INFERENCE, Capability.EMBEDDING})


def _probe(free_mib=16_000, *, calls=None):
    def smi():
        if calls is not None:
            calls.append(1)
        return f"RTX, 16303, {free_mib}\n"
    return HardwareProbe(run_nvidia_smi=smi, read_text=lambda p: "MemTotal: 64000000 kB\nMemAvailable: 32000000 kB\n"
                         if p == "/proc/meminfo" else None,
                         disk_free=lambda p: 100 * GiB, cpu_count=lambda: 16, env={}, exists=lambda p: False,
                         clock=lambda: NOW)


def _config(**providers):
    data = {"providers": {"primary": {"provider": "ollama", "model": "qwen3:8b"}, **providers}}
    return ZygosConfig.model_validate(data)


def _catalog(tmp_path, provider, *, config=None, probe=None, voice=lambda: None, extra=None):
    store = ProfileStore(tmp_path / "profiles")
    store.load_all()
    providers = {"ollama": provider} if provider is not None else {}
    providers.update(extra or {})
    return ModelCatalog(providers=providers, profiles=store, hardware=probe or _probe(),
                        config=config or _config(), voice_snapshot=voice, clock=lambda: NOW), store


def _ctx(events=None):
    bus = InProcessEventBus()
    if events is not None:
        async def collect(event):
            events.append(event)
        bus.subscribe(collect)
    return root_context(bus)


def _by_name(view):
    return {m.name: m for m in view.models}


@pytest.mark.asyncio
async def test_view_creates_profiles_and_fits(tmp_path):
    ollama = FakeOllama(
        tags=[_tag("qwen3:8b", "d1"), _tag("gemma4:e4b", "d2", family="gemma4")],
        running=[OllamaRunning(name="qwen3:8b", digest="d1", size=6 * GiB, size_vram=6 * GiB)])
    catalog, _ = _catalog(tmp_path, ollama)
    view = await catalog.view(_ctx())
    files = sorted(p.name for p in (tmp_path / "profiles" / "ollama").glob("*.json"))
    assert files == ["gemma4_e4b.json", "qwen3_8b.json"]
    assert view.ollama.configured and view.ollama.reachable and view.ollama.error is None
    assert view.hardware is not None and view.hardware.vram_total_bytes is not None
    models = _by_name(view)
    qwen = models["qwen3:8b"]
    assert qwen.location == "local" and qwen.loaded is True and qwen.vram_bytes == 6 * GiB
    assert qwen.fit is not None and qwen.fit.needs.measured is True
    assert qwen.fit_text and "measured" in qwen.fit_text
    assert qwen.primary is True and qwen.fallback is False
    assert qwen.family == "qwen3" and qwen.quantization == "Q4_K_M" and qwen.parameter_size == "8.2B"
    assert qwen.capabilities["tools"] is True and qwen.capabilities["vision"] is False
    assert qwen.fields["identity.family"].source == "ollama"
    assert qwen.fields["identity.num_ctx"].source == "modelfile"
    assert qwen.fields["performance.vram_bytes"].source == "measured"
    gemma = models["gemma4:e4b"]
    assert gemma.loaded is False and gemma.vram_bytes is None and gemma.fit.needs.measured is False
    # local models sorted by family then name
    assert [m.name for m in view.models] == ["gemma4:e4b", "qwen3:8b"]


@pytest.mark.asyncio
async def test_view_shares_profile_for_same_digest(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "same"), _tag("qwen3:latest", "same")])
    catalog, store = _catalog(tmp_path, ollama)
    view = await catalog.view(_ctx())
    files = list((tmp_path / "profiles" / "ollama").glob("*.json"))
    assert len(files) == 1
    on_disk = json.loads(files[0].read_text())
    assert set(on_disk["names"]) == {"qwen3:8b", "qwen3:latest"}
    models = _by_name(view)
    assert set(models) == {"qwen3:8b", "qwen3:latest"}
    assert models["qwen3:8b"].fields == models["qwen3:latest"].fields
    assert ollama.show_calls == ["qwen3:8b"]
    assert store.get("ollama", "qwen3:latest") is store.get("ollama", "qwen3:8b")


@pytest.mark.asyncio
async def test_view_calls_show_only_for_new_or_changed_models(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1"), _tag("gemma4:e4b", "d2", family="gemma4")])
    catalog, _ = _catalog(tmp_path, ollama)
    await catalog.view(_ctx())
    assert sorted(ollama.show_calls) == ["gemma4:e4b", "qwen3:8b"]
    ollama.show_calls.clear()
    await catalog.view(_ctx())
    assert ollama.show_calls == []
    ollama.tags = (_tag("qwen3:8b", "d1-new"), _tag("gemma4:e4b", "d2", family="gemma4"))
    await catalog.view(_ctx())
    assert ollama.show_calls == ["qwen3:8b"]
    saved = json.loads((tmp_path / "profiles" / "ollama" / "qwen3_8b.json").read_text())
    assert saved["digest"] == "d1-new"


@pytest.mark.asyncio
async def test_view_ollama_unreachable_still_answers(tmp_path):
    ollama = FakeOllama(fail=ProviderUnavailable("connection refused", provider="ollama"))
    config = _config(fallbacks=[{"provider": "anthropic", "model": "claude-x"}])
    catalog, _ = _catalog(tmp_path, ollama, config=config, extra={"anthropic": FakeCloud()})
    view = await catalog.view(_ctx())
    assert view.ollama.configured is True and view.ollama.reachable is False
    assert "connection refused" in view.ollama.error
    assert [(m.provider, m.name, m.location) for m in view.models] == [("anthropic", "claude-x", "cloud")]
    assert view.models[0].fallback is True


@pytest.mark.asyncio
async def test_view_without_ollama_configured(tmp_path):
    config = ZygosConfig.model_validate({"providers": {"primary": {"provider": "anthropic", "model": "claude-x"}}})
    catalog, _ = _catalog(tmp_path, None, config=config, extra={"anthropic": FakeCloud()})
    view = await catalog.view(_ctx())
    assert view.ollama.configured is False and view.ollama.reachable is False and view.ollama.error is None
    assert [(m.name, m.primary) for m in view.models] == [("claude-x", True)]


@pytest.mark.asyncio
async def test_view_show_failure_builds_from_tags_only(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")], show_fail=True)
    catalog, _ = _catalog(tmp_path, ollama)
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    assert qwen.family == "qwen3" and qwen.download_size_bytes == 5 * GiB
    assert "identity.kv_bytes_per_token" not in qwen.fields
    assert qwen.fit.level == "unknown"
    assert (tmp_path / "profiles" / "ollama" / "qwen3_8b.json").exists()


@pytest.mark.asyncio
async def test_view_show_failure_on_changed_digest_keeps_values_and_retries(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")])
    catalog, _ = _catalog(tmp_path, ollama)
    await catalog.view(_ctx())
    ollama.tags = (_tag("qwen3:8b", "d2"),)
    ollama.show_fail = True
    ollama.show_calls.clear()
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    assert "identity.kv_bytes_per_token" in qwen.fields and "identity.num_ctx" in qwen.fields
    saved = json.loads((tmp_path / "profiles" / "ollama" / "qwen3_8b.json").read_text())
    assert saved["digest"] == "d1"   # not refreshed, so the next view retries
    ollama.show_fail = False
    await catalog.view(_ctx())
    assert ollama.show_calls == ["qwen3:8b", "qwen3:8b"]
    saved = json.loads((tmp_path / "profiles" / "ollama" / "qwen3_8b.json").read_text())
    assert saved["digest"] == "d2"


@pytest.mark.asyncio
async def test_view_reclaimable_and_kokoro_reserve(tmp_path):
    ollama = FakeOllama(
        tags=[_tag("qwen3:8b", "d1"), _tag("gemma4:e4b", "d2", family="gemma4")],
        running=[OllamaRunning(name="gemma4:e4b", digest="d2", size=3 * GiB, size_vram=3 * GiB)])
    config = ZygosConfig.model_validate({
        "providers": {"primary": {"provider": "ollama", "model": "qwen3:8b"}},
        "voice": {"enabled": True, "tts": {"engine": "kokoro", "device": "cuda"}}})
    free = 4_000  # MiB
    catalog, _ = _catalog(tmp_path, ollama, config=config, probe=_probe(free))
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    expected = free * 1024**2 + 3 * GiB - KOKORO_CUDA_RESERVE_BYTES
    assert qwen.fit.vram_available_bytes == expected

    alive = VoiceState(stt=None, tts=TtsHealth(engine="kokoro", device="cuda", alive=True,
                                                requested_device="cuda"))
    catalog, _ = _catalog(tmp_path, ollama, config=config, probe=_probe(free), voice=lambda: alive)
    view = await catalog.view(_ctx())
    assert _by_name(view)["qwen3:8b"].fit.vram_available_bytes == free * 1024**2 + 3 * GiB


@pytest.mark.asyncio
async def test_view_loaded_model_does_not_count_its_own_vram_twice(tmp_path):
    ollama = FakeOllama(
        tags=[_tag("qwen3:8b", "d1")],
        running=[OllamaRunning(name="qwen3:8b", digest="d1", size=6 * GiB, size_vram=6 * GiB)])
    free = 2_000
    catalog, _ = _catalog(tmp_path, ollama, probe=_probe(free))
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    # free + its own VRAM once (fit adds it for a measured model); not reclaimable on top
    assert qwen.fit.vram_available_bytes == free * 1024**2 + 6 * GiB


@pytest.mark.asyncio
async def test_view_unloaded_measured_model_gets_no_stale_vram_credit(tmp_path):
    ollama = FakeOllama(
        tags=[_tag("qwen3:8b", "d1")],
        running=[OllamaRunning(name="qwen3:8b", digest="d1", size=6 * GiB, size_vram=6 * GiB)])
    free = 2_000
    catalog, _ = _catalog(tmp_path, ollama, probe=_probe(free))
    await catalog.view(_ctx())
    ollama.running = ()  # unloaded since; its profile keeps the measured sizes
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    assert qwen.loaded is False
    assert qwen.fit.vram_available_bytes == free * 1024**2


@pytest.mark.asyncio
async def test_view_lists_cloud_routes_without_fit(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")])
    config = _config(fallbacks=[{"provider": "anthropic", "model": "claude-x"},
                                {"provider": "vllm", "model": "llama-70b"}])
    catalog, _ = _catalog(tmp_path, ollama, config=config,
                          extra={"anthropic": FakeCloud(), "vllm": FakeVllm()})
    view = await catalog.view(_ctx())
    models = _by_name(view)
    cloud = models["claude-x"]
    assert cloud.location == "cloud" and cloud.fit is None and cloud.fit_text is None
    assert cloud.fallback is True and cloud.primary is False
    assert (tmp_path / "profiles" / "anthropic" / "claude-x.json").exists()
    vllm = models["llama-70b"]
    assert vllm.location == "local" and vllm.fit is None
    assert vllm.fit_text == "fit not checked for vllm"
    # cloud entries come after local ones
    assert view.models[-1].name == "claude-x"


@pytest.mark.asyncio
async def test_view_reports_profile_error(tmp_path):
    bad = tmp_path / "profiles" / "ollama" / "qwen3_8b.json"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"{ not json")
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")])
    catalog, _ = _catalog(tmp_path, ollama)
    view = await catalog.view(_ctx())
    qwen = _by_name(view)["qwen3:8b"]
    assert qwen.profile_error
    assert qwen.family == "qwen3"  # listed from the in-memory profile
    assert bad.read_bytes() == b"{ not json"


@pytest.mark.asyncio
async def test_view_emits_model_fit_events(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1"), _tag("gemma4:e4b", "d2", family="gemma4")])
    config = _config(fallbacks=[{"provider": "anthropic", "model": "claude-x"}])
    catalog, _ = _catalog(tmp_path, ollama, config=config, extra={"anthropic": FakeCloud()})
    events = []
    view = await catalog.view(_ctx(events))
    fits = [e for e in events if e.type == "model.fit"]
    assert sorted(e.payload.model for e in fits) == ["gemma4:e4b", "qwen3:8b"]
    assert all(e.source == "models" and e.payload.provider == "ollama" for e in fits)
    qwen = next(e.payload for e in fits if e.payload.model == "qwen3:8b")
    entry = _by_name(view)["qwen3:8b"]
    assert qwen.level == entry.fit.level
    assert qwen.needs_bytes == entry.fit.needs.total_bytes
    assert qwen.free_bytes == entry.fit.vram_available_bytes
    assert qwen.measured is False


@pytest.mark.asyncio
async def test_view_matches_untagged_route_to_latest(tmp_path):
    ollama = FakeOllama(tags=[_tag("qwen3:latest", "d1")])
    config = ZygosConfig.model_validate({"providers": {"primary": {"provider": "ollama", "model": "qwen3"}}})
    catalog, _ = _catalog(tmp_path, ollama, config=config)
    view = await catalog.view(_ctx())
    assert _by_name(view)["qwen3:latest"].primary is True
