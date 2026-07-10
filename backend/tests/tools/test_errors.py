"""M5 C2 Task 1 — tool error taxonomy additions."""

from zygos.errors import ToolError, ToolNotFound, ToolPermissionDenied, ToolTimeout, ZygosError


def test_tool_error_has_retryable_default_false():
    assert ToolError.retryable is False
    assert ToolError().code == "tool_error"


def test_tool_timeout_is_retryable_with_stable_code():
    assert issubclass(ToolTimeout, ToolError)
    assert ToolTimeout("boom").code == "tool_timeout"
    assert ToolTimeout("boom").retryable is True


def test_permission_denied_is_not_retryable():
    assert issubclass(ToolPermissionDenied, ToolError)
    assert ToolPermissionDenied("no").code == "tool_permission_denied"
    assert ToolPermissionDenied("no").retryable is False


def test_tool_not_found_unchanged():
    assert ToolNotFound("x").code == "tool_not_found"
    assert isinstance(ToolTimeout("x"), ZygosError)
