import pytest

from zygos.backends.launch import (
    ZYGOS_FLAGS,
    LaunchError,
    LaunchSettings,
    parse_launch,
    read_launch,
)


def test_parse_basic():
    assert parse_launch("-ngl 20 -ctk q4_0 --n-cpu-moe 8") == [
        "-ngl", "20", "-ctk", "q4_0", "--n-cpu-moe", "8",
    ]


def test_parse_quoted():
    assert parse_launch('--chat-template-file "my file.jinja"') == [
        "--chat-template-file", "my file.jinja",
    ]


def test_parse_empty():
    assert parse_launch("   ") == []


def test_parse_unbalanced():
    with pytest.raises(LaunchError, match="can't read the launch settings"):
        parse_launch('--x "oops')


def test_zygos_flag_list():
    assert ZYGOS_FLAGS == {
        "-m", "--model", "--host", "--port", "-a", "--alias", "--mmproj",
        "-hf", "--hf-repo", "-hff", "--hf-file", "-mu", "--model-url",
    }


@pytest.mark.parametrize("flag", sorted(ZYGOS_FLAGS))
def test_zygos_flags_refused(flag):
    for text in (f"{flag} x", f"-c 10 {flag}=x"):
        with pytest.raises(LaunchError, match=f"{flag} is set by Zygos — remove it"):
            parse_launch(text)


def test_similar_flag_not_refused():
    assert parse_launch("--mmproj-offload") == ["--mmproj-offload"]


@pytest.mark.parametrize("flag", ["-c", "--ctx-size"])
def test_read_ctx(flag):
    assert read_launch([flag, "4096"]).ctx_size == 4096
    assert read_launch([f"{flag}=8192"]).ctx_size == 8192


@pytest.mark.parametrize("flag", ["-ngl", "--n-gpu-layers", "--gpu-layers"])
def test_read_ngl(flag):
    assert read_launch([flag, "20"]).n_gpu_layers == 20
    assert read_launch([f"{flag}=7"]).n_gpu_layers == 7
    assert read_launch([flag, "all"]).n_gpu_layers == "all"
    assert read_launch([flag, "-1"]).n_gpu_layers == "all"
    assert read_launch([flag, "999"]).n_gpu_layers == "all"
    assert read_launch([flag, "0"]).n_gpu_layers == 0


@pytest.mark.parametrize("flag", ["-ctk", "--cache-type-k"])
def test_read_ctk(flag):
    assert read_launch([flag, "q8_0"]).cache_type_k == "q8_0"
    assert read_launch([f"{flag}=q4_0"]).cache_type_k == "q4_0"


@pytest.mark.parametrize("flag", ["-ctv", "--cache-type-v"])
def test_read_ctv(flag):
    assert read_launch([flag, "q8_0"]).cache_type_v == "q8_0"
    assert read_launch([f"{flag}=f16"]).cache_type_v == "f16"


@pytest.mark.parametrize("flag", ["--n-cpu-moe", "-ncmoe"])
def test_read_moe(flag):
    assert read_launch([flag, "8"]).n_cpu_moe == 8
    assert read_launch([f"{flag}=3"]).n_cpu_moe == 3


@pytest.mark.parametrize("flag", ["-np", "--parallel"])
def test_read_parallel(flag):
    assert read_launch([flag, "4"]).parallel == 4
    assert read_launch([f"{flag}=2"]).parallel == 2


@pytest.mark.parametrize("flag", ["--no-kv-offload", "-nkvo"])
def test_read_no_kv_offload(flag):
    assert read_launch([flag]).no_kv_offload is True


def test_read_no_jinja():
    assert read_launch(["--no-jinja"]).jinja_off is True


def test_read_defaults():
    s = read_launch([])
    assert s == LaunchSettings(
        ctx_size=None, n_gpu_layers=None, cache_type_k=None, cache_type_v=None,
        n_cpu_moe=None, parallel=None, no_kv_offload=False, jinja_off=False,
    )


def test_read_garbage_numbers_none():
    s = read_launch(["-c", "lots", "-ngl", "many", "--n-cpu-moe=x", "-np", "1.5"])
    assert s.ctx_size is None and s.n_gpu_layers is None
    assert s.n_cpu_moe is None and s.parallel is None


def test_read_missing_value_none():
    assert read_launch(["-c"]).ctx_size is None


def test_frozen():
    with pytest.raises(Exception):
        read_launch([]).ctx_size = 1
