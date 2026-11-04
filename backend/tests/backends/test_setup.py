import httpx
import pytest

from zygos.backends.settings import (
    BackendsSettings, LlamaCppBackend, OllamaBackend, VllmEndpoint,
)
from zygos.backends.setup import run_backend_setup


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


async def run(answers, store=None, *, run_version=fake_version):
    store = store or Mem()
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
            store, client, current_ollama_url="http://localhost:11434",
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


async def test_no_llamacpp_prints_install_and_leaves_it(server):
    old = BackendsSettings(llamacpp=LlamaCppBackend(server_path=server))
    store, saved, said, _ = await run(["", "n", "n", "y"], Mem(old))
    assert saved
    assert store.value.llamacpp == old.llamacpp
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
    store, saved, _, _ = await run(["http://box:11434"])
    assert not saved and store.sets == 0
