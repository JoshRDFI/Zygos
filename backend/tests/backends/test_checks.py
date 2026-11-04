import os
import stat
import sys

import httpx
import pytest

from zygos.backends.checks import (
    check_llama_server,
    check_ollama,
    check_vllm,
    count_gguf,
)


def client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_ollama_ok():
    async def h(request):
        assert request.url.path == "/api/version"
        return httpx.Response(200, json={"version": "0.9.1"})

    c = await check_ollama(client(h), "http://x:11434")
    assert c.ok and c.detail == "Ollama 0.9.1 at http://x:11434"


async def test_ollama_down():
    def h(request):
        raise httpx.ConnectError("refused")

    c = await check_ollama(client(h), "http://x:11434")
    assert not c.ok and c.detail


async def test_ollama_non_json():
    c = await check_ollama(client(lambda r: httpx.Response(200, text="<html>")), "http://x")
    assert not c.ok


async def test_ollama_bad_status():
    c = await check_ollama(client(lambda r: httpx.Response(500)), "http://x")
    assert not c.ok and "500" in c.detail


async def test_vllm_ok():
    def h(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "a"}, {"id": "b"}]})

    c, ids = await check_vllm(client(h), "http://x:8000/v1")
    assert c.ok and ids == ["a", "b"]


async def test_vllm_down():
    def h(request):
        raise httpx.ConnectError("refused")

    c, ids = await check_vllm(client(h), "http://x:8000/v1")
    assert not c.ok and ids == [] and c.detail


async def test_vllm_non_openai_body():
    c, ids = await check_vllm(client(lambda r: httpx.Response(200, json={"x": 1})), "http://x/v1")
    assert not c.ok and ids == []
    c, ids = await check_vllm(client(lambda r: httpx.Response(200, text="nope")), "http://x/v1")
    assert not c.ok and ids == []


async def test_llama_none():
    c = await check_llama_server(None)
    assert not c.ok and "not set" in c.detail


async def test_llama_missing(tmp_path):
    c = await check_llama_server(str(tmp_path / "nope"))
    assert not c.ok and "not found" in c.detail


async def test_llama_directory(tmp_path):
    c = await check_llama_server(str(tmp_path))
    assert not c.ok and "directory" in c.detail


@pytest.mark.skipif(os.name != "posix", reason="posix perms")
async def test_llama_not_executable(tmp_path):
    p = tmp_path / "llama-server"
    p.write_text("x")
    p.chmod(0o644)
    c = await check_llama_server(str(p))
    assert not c.ok and "not executable" in c.detail


def _file(tmp_path):
    p = tmp_path / "llama-server"
    p.write_text("x")
    p.chmod(0o755)
    return str(p)


async def test_llama_version_from_stderr(tmp_path):
    async def run(cmd):
        path = cmd
        assert path == [p, "--version"]
        return b"", b"\nversion: 6000 (abc123)\nbuilt with gcc\n"

    p = _file(tmp_path)
    c = await check_llama_server(p, run=run)
    assert c.ok and c.detail == "version: 6000 (abc123)"


async def test_llama_timeout(tmp_path):
    import asyncio

    async def run(cmd):
        raise asyncio.TimeoutError

    c = await check_llama_server(_file(tmp_path), run=run)
    assert not c.ok and c.detail == "llama-server didn't answer --version within 5 s"


async def test_llama_run_raises(tmp_path):
    async def run(cmd):
        raise OSError("exec format error")

    c = await check_llama_server(_file(tmp_path), run=run)
    assert not c.ok and "exec format error" in c.detail


async def test_llama_no_output(tmp_path):
    async def run(cmd):
        return b"", b"  \n"

    c = await check_llama_server(_file(tmp_path), run=run)
    assert not c.ok


@pytest.mark.skipif(os.name != "posix", reason="posix script")
async def test_llama_real_script(tmp_path):
    p = tmp_path / "fake-llama"
    p.write_text("#!/bin/sh\necho 'version: 1 (deadbeef)' >&2\n")
    p.chmod(p.stat().st_mode | stat.S_IXUSR)
    c = await check_llama_server(str(p))
    assert c.ok and c.detail == "version: 1 (deadbeef)"


@pytest.mark.skipif(os.name != "posix", reason="posix script")
async def test_llama_real_hang_is_killed(tmp_path, monkeypatch):
    from zygos.backends import checks

    monkeypatch.setattr(checks, "VERSION_TIMEOUT_S", 0.3)
    p = tmp_path / "hang"
    p.write_text("#!/bin/sh\nexec sleep 30\n")
    p.chmod(0o755)
    c = await check_llama_server(str(p))
    assert not c.ok and "didn't answer" in c.detail


def test_count_gguf_none():
    c = count_gguf(None)
    assert not c.ok


def test_count_gguf_missing(tmp_path):
    assert not count_gguf(str(tmp_path / "nope")).ok


def test_count_gguf_file(tmp_path):
    f = tmp_path / "a.gguf"
    f.write_text("x")
    assert not count_gguf(str(f)).ok


def test_count_gguf_nested(tmp_path):
    (tmp_path / "a.gguf").write_text("x")
    (tmp_path / "b.txt").write_text("x")
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "sub" / "c.GGUF").write_text("x")
    (tmp_path / "sub" / "deep" / "d.gguf").write_text("x")
    c = count_gguf(str(tmp_path))
    assert c.ok and c.detail == f"3 GGUF files in {tmp_path}"


def test_count_gguf_one(tmp_path):
    (tmp_path / "a.gguf").write_text("x")
    assert count_gguf(str(tmp_path)).detail == f"1 GGUF files in {tmp_path}"


@pytest.mark.skipif(os.name != "posix" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs non-root posix")
def test_count_gguf_unreadable_subdir(tmp_path):
    (tmp_path / "a.gguf").write_text("x")
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "z.gguf").write_text("x")
    bad.chmod(0)
    try:
        c = count_gguf(str(tmp_path))
    finally:
        bad.chmod(0o755)
    assert c.ok and c.detail == f"1 GGUF files in {tmp_path}"
