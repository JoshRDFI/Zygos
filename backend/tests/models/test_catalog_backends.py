"""ModelCatalog sources for llama.cpp GGUF folders and vLLM (RFC-0014 §3, §9)."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import httpx
import pytest

from tests.models.gguf_writer import write_gguf
from tests.models.test_catalog import NOW, FakeCloud, FakeOllama, FakeVllm, _by_name, _config, _ctx, _probe, _tag
from zygos.backends.settings import BackendsSettings, LlamaCppBackend, VllmEndpoint
from zygos.models.catalog import LOCAL_PROVIDERS, ModelCatalog
from zygos.models.gguf import read_header
from zygos.models.store import ProfileStore

VLLM_URL = "http://gpu:8000/v1"
VLLM_TEXT = "fit not checked: vLLM reserves its GPU share at start"
U32, STR = 4, 8


class FakeBackends:
    def __init__(self, settings: BackendsSettings) -> None:
        self.settings = settings

    def get(self) -> BackendsSettings:
        return self.settings

    def set(self, settings: BackendsSettings) -> None:  # pragma: no cover - never called
        raise AssertionError("the catalog never writes the backends record")


def _meta(arch="qwen3", blocks=2, *, split_count=None):
    kvs = [("general.architecture", STR, arch), ("general.file_type", U32, 15),
           (f"{arch}.block_count", U32, blocks), (f"{arch}.context_length", U32, 40960),
           (f"{arch}.attention.head_count_kv", U32, 8), (f"{arch}.attention.key_length", U32, 128),
           (f"{arch}.attention.value_length", U32, 128)]
    if split_count is not None:
        kvs.append(("split.count", 2, split_count))  # uint16
    return kvs


def _tensors(names, size=1024):
    return [(n, [4], 0, i * size) for i, n in enumerate(names)], size


def _gguf(path: Path, names, *, kvs=None, size=1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tensors, size = _tensors(names, size)
    return write_gguf(path, _meta() if kvs is None else kvs, tensors, data_size=size * len(names))


def _folder(root: Path) -> Path:
    """Big: split in two parts (layer 0 + other in part 1, layer 1 in part 2).
    sub/Vis: one file plus a paired projector."""
    _gguf(root / "Big-00001-of-00002.gguf", ["token_embd.weight", "blk.0.attn_q.weight"],
          kvs=_meta(split_count=2))
    _gguf(root / "Big-00002-of-00002.gguf", ["blk.1.attn_q.weight"], kvs=[("split.count", 2, 2)])
    _gguf(root / "sub" / "Vis.gguf", ["token_embd.weight", "blk.0.attn_q.weight", "blk.1.attn_q.weight"])
    (root / "sub" / "mmproj-vis-f16.gguf").write_bytes(b"P" * 2048)
    return root


def _client(handler, calls=None):
    def wrapped(request):
        if calls is not None:
            calls.append(str(request.url))
        return handler(request)
    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped))


def _served(*models):
    return lambda r: httpx.Response(200, json={"object": "list", "data": list(models)})


def _catalog(tmp_path, *, settings=None, ollama=None, config=None, client=None, reader=read_header,
             extra=None):
    store = ProfileStore(tmp_path / "profiles")
    store.load_all()
    providers = {"ollama": ollama} if ollama is not None else {}
    providers.update(extra or {})
    catalog = ModelCatalog(
        providers=providers, profiles=store, hardware=_probe(), config=config or _config(),
        voice_snapshot=lambda: None, clock=lambda: NOW,
        backends=FakeBackends(settings) if settings is not None else None,
        client=client, read_header=reader)
    return catalog, store


def _lc(root, default="", **own):
    return BackendsSettings(llamacpp=LlamaCppBackend(models_dir=str(root), default_args=default, model_args=own))


def test_llamacpp_is_a_local_provider():
    assert "llamacpp" in LOCAL_PROVIDERS


@pytest.mark.asyncio
async def test_llamacpp_models_listed_with_profiles_fits_and_launch_text(tmp_path):
    root = _folder(tmp_path / "gguf")
    settings = _lc(root, "-c 8192", **{"sub/Vis": "-c 2048 -ngl 1"})
    catalog, _ = _catalog(tmp_path, settings=settings)
    events = []
    view = await catalog.view(_ctx(events))
    lc = [m for m in view.models if m.provider == "llamacpp"]
    assert [m.name for m in lc] == ["Big", "sub/Vis"]
    big, vis = lc
    assert big.location == "local" and big.loaded is False and big.vram_bytes is None
    assert big.profile_error is None and big.family == "qwen3" and big.quantization == "Q4_K_M"
    assert big.launch_text == "-c 8192" and big.launch_source == "default" and big.launch_error is None
    assert big.download_size_bytes == sum(f.stat().st_size for f in root.glob("Big-*.gguf"))
    # tensors of both split parts are counted
    assert set(big.fields["identity.tensor_bytes"].value["layers"]) == {"0", "1"}
    assert big.fields["identity.family"].source == "modelfile"
    assert big.fit.level == "gpu" and big.fit.needs.context_tokens == 8192
    assert big.fit_text.startswith("needs ≈")
    assert big.mmproj is None and big.mmproj_ambiguous == ()

    assert vis.launch_text == "-c 2048 -ngl 1" and vis.launch_source == "model"
    assert vis.mmproj == "sub/mmproj-vis-f16.gguf"
    assert vis.capabilities["vision"] is True
    assert vis.fit.needs.context_tokens == 2048
    assert vis.fit.split_by == "settings" and vis.fit.level == "partial"
    assert "split by your settings" in vis.fit_text

    files = sorted(p.name for p in (tmp_path / "profiles" / "llamacpp").glob("*.json"))
    assert files == ["Big.json", "sub_Vis.json"]
    fits = {e.payload.model: e for e in events if e.type == "model.fit" and e.payload.provider == "llamacpp"}
    assert set(fits) == {"Big", "sub/Vis"}
    assert fits["Big"].source == "models"
    assert fits["Big"].payload.level == "gpu" and fits["Big"].payload.needs_bytes == big.fit.needs.total_bytes


@pytest.mark.asyncio
async def test_ambiguous_projectors_are_listed_on_each_model(tmp_path):
    root = tmp_path / "gguf"
    _gguf(root / "d" / "A.gguf", ["blk.0.attn_q.weight"])
    _gguf(root / "d" / "B.gguf", ["blk.0.attn_q.weight"])
    (root / "d" / "mmproj-x.gguf").write_bytes(b"P")
    (root / "d" / "mmproj-y.gguf").write_bytes(b"P")
    catalog, _ = _catalog(tmp_path, settings=_lc(root))
    models = _by_name(await catalog.view(_ctx()))
    for name in ("d/A", "d/B"):
        assert models[name].mmproj is None
        assert models[name].mmproj_ambiguous == ("d/mmproj-x.gguf", "d/mmproj-y.gguf")


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"not a gguf at all, just text....", b"GGUF\x03\x00", b"GGUF\x09\x00\x00\x00" + b"\0" * 40])
async def test_unreadable_gguf_gets_profile_error_and_others_listed(tmp_path, content):
    root = _folder(tmp_path / "gguf")
    (root / "Broken.gguf").write_bytes(content)
    catalog, _ = _catalog(tmp_path, settings=_lc(root))
    events = []
    models = _by_name(await catalog.view(_ctx(events)))
    broken = models["Broken"]
    assert broken.profile_error.startswith("can't read GGUF header: ")
    assert broken.fit is None and broken.provider == "llamacpp"
    assert not (tmp_path / "profiles" / "llamacpp" / "Broken.json").exists()
    assert models["Big"].profile_error is None and models["sub/Vis"].fit is not None
    assert "Broken" not in {e.payload.model for e in events if e.type == "model.fit"}


@pytest.mark.asyncio
async def test_incomplete_split_set_is_a_header_error(tmp_path):
    root = tmp_path / "gguf"
    _gguf(root / "Half-00001-of-00002.gguf", ["blk.0.attn_q.weight"], kvs=_meta(split_count=2))
    catalog, _ = _catalog(tmp_path, settings=_lc(root))
    half = _by_name(await catalog.view(_ctx()))["Half"]
    assert half.profile_error == "can't read GGUF header: split set has 1 of 2 parts"


@pytest.mark.asyncio
@pytest.mark.parametrize("text, message", [
    ("-c 'unbalanced", "can't read the launch settings: No closing quotation"),
    ("-c 4096 --port=9000", "--port is set by Zygos — remove it"),
])
async def test_bad_launch_text_gives_launch_error_and_unknown_fit(tmp_path, text, message):
    root = _folder(tmp_path / "gguf")
    catalog, _ = _catalog(tmp_path, settings=_lc(root, text))
    events = []
    big = _by_name(await catalog.view(_ctx(events)))["Big"]
    assert big.launch_error == message and big.launch_text == text and big.launch_source == "default"
    assert big.fit.level == "unknown" and big.fit.reason == f"launch settings: {message}"
    assert big.fit_text == f"launch settings: {message}"
    assert big.profile_error is None and big.family == "qwen3"
    assert "Big" in {e.payload.model for e in events if e.type == "model.fit"}


@pytest.mark.asyncio
async def test_unchanged_files_read_no_headers_and_changed_digest_refreshes(tmp_path):
    root = _folder(tmp_path / "gguf")
    (root / "Broken.gguf").write_bytes(b"junk" * 10)
    reads: list[Path] = []
    threads: set[str] = set()

    def reader(path):
        reads.append(path)
        threads.add(threading.current_thread().name)
        return read_header(path)

    catalog, _ = _catalog(tmp_path, settings=_lc(root), reader=reader)
    await catalog.view(_ctx())
    assert sorted(p.name for p in reads) == [
        "Big-00001-of-00002.gguf", "Big-00002-of-00002.gguf", "Broken.gguf", "Vis.gguf"]
    assert threading.main_thread().name not in threads  # header reads run off the event loop
    reads.clear()
    await catalog.view(_ctx())
    assert reads == []

    # The user section survives a digest-change refresh.
    path = tmp_path / "profiles" / "llamacpp" / "sub_Vis.json"
    data = json.loads(path.read_text())
    data["user"] = {"notes": "mine"}
    path.write_text(json.dumps(data))
    vis = root / "sub" / "Vis.gguf"
    st = vis.stat()
    os.utime(vis, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))
    models = _by_name(await catalog.view(_ctx()))
    assert [p.name for p in reads] == ["Vis.gguf"]
    assert json.loads(path.read_text())["user"] == {"notes": "mine"}
    assert models["sub/Vis"].fields["notes"].source == "user"


@pytest.mark.asyncio
async def test_llamacpp_profile_save_error_never_fails_the_view(tmp_path, monkeypatch):
    root = _folder(tmp_path / "gguf")
    catalog, store = _catalog(tmp_path, settings=_lc(root))

    def boom(profile):
        raise OSError("read-only file system")
    monkeypatch.setattr(store, "save", boom)
    models = _by_name(await catalog.view(_ctx()))
    assert models["Big"].profile_error == "profile can't be saved: read-only file system"
    assert models["Big"].fit is not None and models["Big"].family == "qwen3"


@pytest.mark.asyncio
@pytest.mark.parametrize("where", ["missing", "file"])
async def test_missing_models_dir_lists_no_llamacpp_entries(tmp_path, where):
    target = tmp_path / "nope"
    if where == "file":
        target.write_text("x")
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")])
    catalog, _ = _catalog(tmp_path, settings=_lc(target), ollama=ollama)
    view = await catalog.view(_ctx())
    assert [m.name for m in view.models] == ["qwen3:8b"]
    assert view.models[0].fit is not None


@pytest.mark.asyncio
async def test_vllm_served_models_listed_and_configured_route_merged(tmp_path):
    calls: list[str] = []
    client = _client(_served({"id": "Qwen/Qwen3-8B", "max_model_len": 32768}, {"id": "other"}), calls)
    config = _config(fallbacks=[{"provider": "vllm", "model": "Qwen/Qwen3-8B"}])
    settings = BackendsSettings(vllm=[VllmEndpoint(base_url=VLLM_URL)])
    catalog, _ = _catalog(tmp_path, settings=settings, ollama=FakeOllama(tags=[_tag("qwen3:8b", "d1")]),
                          config=config, client=client, extra={"vllm": FakeVllm()})
    view = await catalog.view(_ctx())
    await client.aclose()
    assert calls == [f"{VLLM_URL}/models"]
    vllm = [m for m in view.models if m.provider == "vllm"]
    assert [m.name for m in vllm] == ["Qwen/Qwen3-8B", "other"]
    qwen, other = vllm
    assert qwen.location == "local" and qwen.fit is None and qwen.fit_text == VLLM_TEXT
    assert qwen.served_by == VLLM_URL and qwen.fallback is True and qwen.primary is False
    assert qwen.fields["identity.context_length_max"].value == 32768
    assert qwen.fields["identity.context_length_max"].source == "server"
    assert other.fallback is False and "identity.context_length_max" not in other.fields
    assert (tmp_path / "profiles" / "vllm" / "Qwen_Qwen3-8B.json").exists()


@pytest.mark.asyncio
async def test_vllm_route_not_served_says_so(tmp_path):
    client = _client(_served({"id": "other"}))
    config = _config(fallbacks=[{"provider": "vllm", "model": "missing"}])
    settings = BackendsSettings(vllm=[VllmEndpoint(base_url=VLLM_URL)])
    catalog, _ = _catalog(tmp_path, settings=settings, config=config, client=client,
                          extra={"vllm": FakeVllm()})
    models = _by_name(await catalog.view(_ctx()))
    await client.aclose()
    assert models["missing"].fit_text == f"not served by vLLM at {VLLM_URL}"
    assert models["missing"].fallback is True and models["missing"].fit is None


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", [
    lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")),
    lambda r: httpx.Response(200, json={"not": "openai"}),
    lambda r: httpx.Response(200, text="<html>"),
])
async def test_vllm_unreachable_is_one_entry_and_the_rest_unaffected(tmp_path, handler):
    client = _client(handler)
    config = _config(fallbacks=[{"provider": "vllm", "model": "Qwen/Qwen3-8B"}])
    settings = BackendsSettings(vllm=[VllmEndpoint(base_url=VLLM_URL)])
    ollama = FakeOllama(tags=[_tag("qwen3:8b", "d1")])
    catalog, _ = _catalog(tmp_path, settings=settings, ollama=ollama, config=config, client=client,
                          extra={"vllm": FakeVllm()})
    view = await catalog.view(_ctx())
    await client.aclose()
    assert view.ollama.reachable is True
    models = _by_name(view)
    assert models["qwen3:8b"].fit is not None and models["qwen3:8b"].primary is True
    down = models[VLLM_URL]
    assert down.provider == "vllm" and down.served_by == VLLM_URL and down.fit is None
    assert down.fit_text.startswith("vLLM unreachable: ") and len(down.fit_text) > len("vLLM unreachable: ")
    route = models["Qwen/Qwen3-8B"]
    assert route.fallback is True and route.fit_text == down.fit_text


@pytest.mark.asyncio
async def test_ordering_ollama_llamacpp_vllm_cloud(tmp_path):
    root = _folder(tmp_path / "gguf")
    client = _client(_served({"id": "served"}))
    config = _config(fallbacks=[{"provider": "anthropic", "model": "claude-x"}])
    settings = BackendsSettings(llamacpp=LlamaCppBackend(models_dir=str(root)),
                                vllm=[VllmEndpoint(base_url=VLLM_URL)])
    catalog, _ = _catalog(tmp_path, settings=settings, ollama=FakeOllama(tags=[_tag("qwen3:8b", "d1")]),
                          config=config, client=client, extra={"anthropic": FakeCloud()})
    view = await catalog.view(_ctx())
    await client.aclose()
    assert [(m.provider, m.name) for m in view.models] == [
        ("ollama", "qwen3:8b"), ("llamacpp", "Big"), ("llamacpp", "sub/Vis"),
        ("vllm", "served"), ("anthropic", "claude-x")]


@pytest.mark.asyncio
async def test_no_backends_set_up_gives_the_same_view_as_before(tmp_path):
    config = _config(fallbacks=[{"provider": "anthropic", "model": "claude-x"},
                                {"provider": "llamacpp", "model": "llama-70b"}])
    extra = {"anthropic": FakeCloud()}

    async def view(sub, **kw):
        catalog, _ = _catalog(tmp_path / sub, ollama=FakeOllama(tags=[_tag("qwen3:8b", "d1")]),
                              config=config, extra=extra, **kw)
        return (await catalog.view(_ctx())).model_dump()

    client = _client(lambda r: pytest.fail("no backend is set up; nothing to ask"))
    before = await view("a")
    after = await view("b", settings=BackendsSettings(), client=client)
    await client.aclose()
    assert before == after
    assert _by_name_dump(after)["llama-70b"]["fit_text"] == "fit not checked for llamacpp"


def _by_name_dump(dump):
    return {m["name"]: m for m in dump["models"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("credentials, url", [
    ({"vllm": {"base_url": "http://cfgv:2/v1"}}, "http://cfgv:2/v1"),
    ({}, "http://localhost:8000/v1"),
])
async def test_config_only_vllm_route_lists_the_served_model(tmp_path, credentials, url):
    """AC10: a vLLM route in the config is enough; its address resolves like startup's."""
    calls: list[str] = []
    client = _client(_served({"id": "Qwen/Qwen3-8B"}), calls)
    config = _config(fallbacks=[{"provider": "vllm", "model": "Qwen/Qwen3-8B"}],
                     credentials=credentials)
    catalog, _ = _catalog(tmp_path, settings=BackendsSettings(), config=config, client=client,
                          extra={"vllm": FakeVllm()})
    models = _by_name(await catalog.view(_ctx()))
    await client.aclose()
    assert calls == [f"{url}/models"]
    qwen = models["Qwen/Qwen3-8B"]
    assert qwen.served_by == url and qwen.fit_text == VLLM_TEXT and qwen.fallback is True


@pytest.mark.asyncio
async def test_installed_records_vllm_served_ids(tmp_path):
    client = _client(_served({"id": "Qwen/Qwen3-8B"}, {"id": "other"}))
    settings = BackendsSettings(vllm=[VllmEndpoint(base_url=VLLM_URL)])
    catalog, _ = _catalog(tmp_path, settings=settings, client=client, extra={"vllm": FakeVllm()})
    assert catalog.installed("vllm") is None
    await catalog.view(_ctx())
    await client.aclose()
    assert catalog.installed("vllm") == frozenset({"Qwen/Qwen3-8B", "other"})


@pytest.mark.asyncio
async def test_installed_vllm_unknown_while_unreachable(tmp_path):
    client = _client(lambda r: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    settings = BackendsSettings(vllm=[VllmEndpoint(base_url=VLLM_URL)])
    catalog, _ = _catalog(tmp_path, settings=settings, client=client, extra={"vllm": FakeVllm()})
    await catalog.view(_ctx())
    await client.aclose()
    assert catalog.installed("vllm") is None
