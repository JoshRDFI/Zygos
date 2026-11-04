import httpx
import pytest

from zygos.backends.settings import (
    BackendsSettings, LlamaCppBackend, OllamaBackend, VllmEndpoint,
)
from zygos.backends.addresses import BACKEND_ADDRESSES, resolve_address
from zygos.backends.setup import run_backend_setup
from zygos.config.schema import ZygosConfig


class Mem:
    def __init__(self, initial=None):
        self.value = initial or BackendsSettings()
        self.sets = 0

    def get(self):
        return self.value

    def set(self, s):
        self.value = s
        self.sets += 1


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/api/version"):
        return httpx.Response(200, json={"version": "0.9"})
    if request.url.path.endswith("/models"):
        return httpx.Response(200, json={"data": [{"id": "qwen"}]})
    return httpx.Response(404)


async def fake_version(cmd):
    return b"version: 1234\n", b""


def _started(config, settings):
    """The addresses a server started with ``settings`` saved would be using."""
    return {n: resolve_address(config, n, settings)[0] for n in BACKEND_ADDRESSES}


async def run(answers, store=None, *, run_version=fake_version, config=None):
    store = store or Mem()
    config = config or ZygosConfig()
    said, prompts = [], []
    it = iter(answers)

    def ask(prompt):
        prompts.append(prompt)
        try:
            return next(it)
        except StopIteration:
            raise EOFError from None

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        saved = await run_backend_setup(
            store, client, config=config, addresses_at_start=_started(config, store.get()),
            ask=ask, say=said.append, run_version=run_version,
        )
    return store, saved, said, prompts


@pytest.fixture
def server(tmp_path):
    p = tmp_path / "llama-server"
    p.write_text("#!/bin/sh\n")
    p.chmod(0o755)
    return str(p)


async def test_happy_path_saves_exact_record(tmp_path, server):
    models = tmp_path / "gguf"
    models.mkdir()
    (models / "a.gguf").write_bytes(b"x")
    store, saved, said, prompts = await run([
        "http://box:11434", "y", server, str(models), "-c 8192 --flash-attn",
        "y", "http://box:8000/v1", "y",
    ])
    assert saved
    assert store.value == BackendsSettings(
        ollama=OllamaBackend(base_url="http://box:11434"),
        llamacpp=LlamaCppBackend(server_path=server, models_dir=str(models),
                                 default_args="-c 8192 --flash-attn"),
        vllm=[VllmEndpoint(name="vllm", base_url="http://box:8000/v1")],
    )
    assert prompts[0] == "Ollama address (Enter keeps http://localhost:11434): "
    assert "Do you have llama.cpp installed? [y/N]: " in prompts
    assert "Default launch settings (as typed after llama-server; Enter for none): " in prompts
    assert "Do you run a vLLM server? [y/N]: " in prompts
    assert prompts[-1] == "Save these settings? [y/N]: "
    assert any("1 GGUF files" in s for s in said)
    assert any("qwen" in s for s in said)
    assert "Restart Zygos for address changes to apply." in said


async def test_no_llamacpp_prints_install_when_nothing_saved():
    store, saved, said, _ = await run(["", "n", "n", "y"])
    assert saved
    assert store.value.llamacpp == LlamaCppBackend()
    assert ("llama.cpp isn't set up. Install it from https://github.com/ggml-org/llama.cpp "
            "(releases or build instructions), then run `zygos personalize backends`.") in said
    assert "Restart Zygos for address changes to apply." not in said


async def test_bad_path_then_enter_keeps_unset():
    store, saved, said, _ = await run(["", "y", "/nope/llama-server", "", "", "", "n", "y"])
    assert saved
    assert store.value.llamacpp.server_path is None
    assert any("not found" in s for s in said)


async def test_bad_path_twice_goes_on_unset():
    store, _, said, _ = await run(["", "y", "/nope/a", "/nope/b", "", "", "n", "y"])
    assert store.value.llamacpp.server_path is None
    assert "Keeping the llama-server path unset." in said


async def test_bad_launch_text_reasked(server):
    store, saved, said, _ = await run(
        ["", "y", server, "", "--port 9000", "'oops", "-c 4096", "n", "y"]
    )
    assert saved
    assert store.value.llamacpp.default_args == "-c 4096"
    assert any("--port is set by Zygos" in s for s in said)
    assert any("can't read the launch settings" in s for s in said)


async def test_declining_confirm_saves_nothing():
    store, saved, said, _ = await run(["http://box:11434", "n", "n", "n"])
    assert not saved and store.sets == 0
    assert any(s.startswith("Ollama: http://box:11434") for s in said)


async def test_eof_saves_nothing():
    store, saved, said, _ = await run(["http://box:11434"])
    assert not saved and store.sets == 0
    assert "Nothing was saved." in said


async def test_declining_llamacpp_and_vllm_clears_saved_on_confirm(server):
    old = BackendsSettings(
        llamacpp=LlamaCppBackend(server_path=server, models_dir="/m", default_args="-c 1",
                                 model_args={"a": "-c 2"}),
        vllm=[VllmEndpoint(base_url="http://box:8000/v1")],
    )
    store, saved, said, _ = await run(["", "n", "n", "y"], Mem(old))
    assert saved
    assert store.value.llamacpp == LlamaCppBackend() and store.value.vllm == []
    assert "llama.cpp: not set up" in said and "vLLM: not set up" in said
    assert not any("isn't set up" in s for s in said)


async def test_declining_saved_then_not_confirming_keeps_saved(server):
    old = BackendsSettings(llamacpp=LlamaCppBackend(server_path=server),
                           vllm=[VllmEndpoint(base_url="http://box:8000/v1")])
    store, saved, _, _ = await run(["", "n", "n", "n"], Mem(old))
    assert not saved and store.value == old and store.sets == 0


async def test_two_bad_paths_keep_saved_path(server):
    old = BackendsSettings(llamacpp=LlamaCppBackend(server_path=server))
    store, _, said, _ = await run(["", "y", "/nope/a", "/nope/b", "", "", "n", "y"], Mem(old))
    assert store.value.llamacpp.server_path == server
    assert "Keeping the current llama-server path." in said


async def test_enter_keeps_existing_llamacpp_and_vllm(server):
    old = BackendsSettings(
        llamacpp=LlamaCppBackend(server_path=server, models_dir="/m", default_args="-c 1",
                                 model_args={"a": "-c 2"}),
        vllm=[VllmEndpoint(base_url="http://box:8000/v1")],
    )
    store, saved, said, _ = await run(["", "y", "", "", "", "y", "", "y"], Mem(old))
    assert saved and store.value == old
    assert "Restart Zygos for address changes to apply." not in said


async def test_vllm_unreachable_says_why_and_still_records():
    def down(request):
        raise httpx.ConnectError("refused")

    store = Mem()
    said = []
    answers = iter(["", "n", "y", "http://box:8000/v1", "y"])
    async with httpx.AsyncClient(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"version": "1"}) if "api/version" in r.url.path
            else down(r))) as client:
        await run_backend_setup(store, client, config=ZygosConfig(),
                                addresses_at_start=_started(ZygosConfig(), store.get()),
                                ask=lambda p: next(answers), say=said.append,
                                run_version=fake_version)
    assert any("can't read models from http://box:8000/v1" in s for s in said)
    assert store.value.vllm[0].base_url == "http://box:8000/v1"


async def test_restart_line_not_printed_when_address_is_in_force():
    _, saved, said, _ = await run(["http://localhost:11434", "n", "n", "y"])
    assert saved
    assert "Restart Zygos for address changes to apply." not in said


CFG = ZygosConfig.model_validate({"providers": {"credentials": {
    "ollama": {"base_url": "http://cfg:1"}, "vllm": {"base_url": "http://cfgv:2/v1"}}}})


async def test_current_ollama_address_includes_config_credential():
    _, _, said, prompts = await run(["", "n", "n", "n"], config=CFG)
    assert prompts[0] == "Ollama address (Enter keeps http://cfg:1): "


async def test_restart_line_follows_the_shared_rule():
    # vLLM recorded at the address the config already gives: nothing changes on restart
    store, saved, said, _ = await run(["", "n", "y", "http://cfgv:2/v1", "y"], config=CFG)
    assert saved and store.value.vllm[0].base_url == "http://cfgv:2/v1"
    assert "Restart Zygos for address changes to apply." not in said


async def test_paths_are_expanded_and_bare_server_name_found_on_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "gguf").mkdir(parents=True)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "llama-server"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(bindir))
    store, saved, said, _ = await run(["", "y", "llama-server", "~/gguf", "", "n", "y"])
    assert saved
    assert store.value.llamacpp.server_path == str(exe)
    assert store.value.llamacpp.models_dir == str(home / "gguf")
    assert f"Models: 0 GGUF files in {home / 'gguf'}" in said


async def test_bad_models_folder_is_asked_again_once(server, tmp_path):
    good = tmp_path / "gguf"
    good.mkdir()
    store, saved, said, prompts = await run(
        ["", "y", server, str(tmp_path / "nofolder"), str(good), "", "n", "y"])
    assert saved and store.value.llamacpp.models_dir == str(good)
    assert prompts.count("GGUF models folder (Enter keeps not set): ") == 2
    assert any("is not a folder" in s for s in said)


async def test_two_bad_models_folders_keep_going_unset(server, tmp_path):
    store, saved, said, prompts = await run(
        ["", "y", server, str(tmp_path / "a"), str(tmp_path / "b"), "", "n", "y"])
    assert saved and store.value.llamacpp.models_dir is None
    assert prompts.count("GGUF models folder (Enter keeps not set): ") == 2
    assert "Keeping the models folder unset." in said
