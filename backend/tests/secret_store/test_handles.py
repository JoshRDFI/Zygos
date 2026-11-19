import pytest

from zygos.secrets import InvalidHandle, validate_handle


@pytest.mark.parametrize(
    "h",
    [
        "provider:anthropic",
        "mcp:search:env:SEARCH_API_KEY",
        "mcp:comfyui:header:Authorization",
    ],
)
def test_valid_handles(h):
    assert validate_handle(h) == h


@pytest.mark.parametrize(
    "h",
    [
        "", "provider:", "provider:a:b", "mcp:s:env:", "mcp::env:X", "mcp:s:cookie:X",
        "mcp:s:env:A B", "mcp:s:env:A\nB", "mcp:s:env:A\x00", "other:x", "mcp:s:env",
        "mcp:" + "s" * 300 + ":env:X",
    ],
)
def test_invalid_handles(h):
    with pytest.raises(InvalidHandle):
        validate_handle(h)


def test_package_import_pulls_no_optional_libraries():
    import subprocess
    import sys

    code = (
        "import sys, zygos.secrets\n"
        "print(','.join(m for m in ('keyring','cryptography') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""


# -- the error never echoes something that may be a secret ---------------


def test_invalid_handle_without_colon_is_not_shown():
    # e.g. set(value, handle) with the arguments swapped
    with pytest.raises(InvalidHandle) as ei:
        validate_handle("sk-ant-SENTINEL-123")
    assert "SENTINEL" not in str(ei.value)
    assert "(not shown)" in str(ei.value)


def test_invalid_handle_with_colon_is_shown_truncated():
    with pytest.raises(InvalidHandle) as ei:
        validate_handle("provider:has space")
    assert "'provider:has space'" in str(ei.value)
    long = "mcp:" + "x" * 100
    with pytest.raises(InvalidHandle) as ei:
        validate_handle(long + " ")
    shown = str(ei.value).split("'")[1]
    assert len(shown) <= 40 and shown.endswith("...")


# -- boundaries and echo rule ------------------------------------


def test_handle_length_boundary():
    ok = "provider:" + "a" * (256 - len("provider:"))
    assert len(ok) == 256 and validate_handle(ok) == ok
    with pytest.raises(InvalidHandle):
        validate_handle(ok + "a")


@pytest.mark.parametrize("h", ["provider:a\x7fb", "provider:a\tb", "mcp:s:env:X:extra"])
def test_more_invalid_handles(h):
    with pytest.raises(InvalidHandle):
        validate_handle(h)


def test_input_with_colon_but_no_handle_prefix_is_not_shown():
    # a swapped-in connection string has a ':' but is not a handle
    with pytest.raises(InvalidHandle) as ei:
        validate_handle("postgres://user:SENTINEL@db")
    assert "SENTINEL" not in str(ei.value) and "(not shown)" in str(ei.value)


@pytest.mark.parametrize("bad", [None, 42, b"provider:x"])
def test_non_string_handle_is_invalid_and_not_shown(bad):
    with pytest.raises(InvalidHandle) as ei:
        validate_handle(bad)  # type: ignore[arg-type]
    assert "(not shown)" in str(ei.value)
