"""Tool contract data models and ToolContext (ARCHITECTURE §Tool Contract; RFC-0002).

Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from zygos.runtime.context import ExecutionContext
from zygos.runtime.events import EventPayload


PermissionDecision = Literal["allow", "deny", "ask"]


class RetryPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    attempts: int = Field(default=1, ge=1)   # 1 == no retry; must be >= 1 (a stream must always yield a terminal chunk)
    backoff_ms: int = 250      # matches router default
    multiplier: float = 2.0    # exponential, matches router


class ToolMeta(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel] | None = None
    retry: RetryPolicy = RetryPolicy()
    timeout_s: float | None = None
    permission: PermissionDecision = "allow"
    fallback: str | None = None


class ToolCall(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tool: str
    args: dict[str, Any] = {}
    call_id: str | None = None


class VerifyResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    reason: str | None = None


class ToolResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    tool: str
    call_id: str
    ok: bool
    output: Any | None = None
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def succeeded(cls, *, tool: str, call_id: str, output: Any) -> "ToolResult":
        return cls(tool=tool, call_id=call_id, ok=True, output=output)

    @classmethod
    def failed(
        cls, *, tool: str, call_id: str, error_code: str, error_message: str | None
    ) -> "ToolResult":
        return cls(
            tool=tool,
            call_id=call_id,
            ok=False,
            error_code=error_code,
            error_message=error_message,
        )


class ToolChunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    kind: Literal["content", "result"]
    content: Any | None = None       # set when kind == "content"
    result: ToolResult | None = None   # terminal; always the last chunk of a stream


@dataclass(frozen=True)
class ToolContext:
    """Per-call context derived from ExecutionContext. Holds NO service refs (RFC-0002).

    `exec` is a child span of the caller's context (span_id == call_id). `emit`/`cancelled`
    passthrough are present but unused in M5 C1 (no events emitted this cycle).
    """

    exec: ExecutionContext
    tool: str
    call_id: str

    @property
    def cancelled(self) -> bool:
        return self.exec.cancelled

    async def emit(self, payload: EventPayload, *, source: str) -> None:
        await self.exec.emit(payload, source=source)


@runtime_checkable
class Tool(Protocol):
    """Four-phase tool contract (ARCHITECTURE §Tool Contract).

    Only `execute` is mandatory; `prepare`/`verify`/`cleanup` default via BaseTool.
    `prepare`/`verify`/`cleanup` are synchronous; `execute` is async.
    """

    meta: ToolMeta

    def prepare(self, ctx: ToolContext) -> None: ...
    async def execute(self, input: BaseModel, ctx: ToolContext) -> Any: ...
    def verify(self, output: Any, ctx: ToolContext) -> VerifyResult: ...
    def cleanup(self, ctx: ToolContext) -> None: ...
    def execute_stream(self, input: BaseModel, ctx: ToolContext) -> AsyncIterator[Any]: ...


class BaseTool:
    """Convenience base supplying default phases so trivial tools write only meta+execute."""

    meta: ToolMeta

    def prepare(self, ctx: ToolContext) -> None:
        return None

    def verify(self, output: Any, ctx: ToolContext) -> VerifyResult:
        if self.meta.output_model is None:
            return VerifyResult(passed=True)
        try:
            self.meta.output_model.model_validate(output)
        except ValidationError as exc:
            return VerifyResult(passed=False, reason=str(exc))
        return VerifyResult(passed=True)

    def cleanup(self, ctx: ToolContext) -> None:
        return None

    async def execute_stream(self, input: BaseModel, ctx: ToolContext) -> AsyncIterator[Any]:
        """Default: wrap `execute` as a single-value stream so every tool is streamable."""
        yield await self.execute(input, ctx)
