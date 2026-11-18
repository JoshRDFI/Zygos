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
