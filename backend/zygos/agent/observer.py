"""Observation hook for the agentic loop (M8 C3).

Neutral, api-free events the turn loop translates into `tools:*` frames. Purely
observational: dropping the observer changes only what the client sees, never the loop's
control flow, result, or error handling. Stability: Experimental.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Union

from zygos.tools.types import ToolResult


@dataclass(frozen=True)
class ToolCallStarted:
    call_id: str
    name: str
    arguments: dict


@dataclass(frozen=True)
class ToolCallFinished:
    call_id: str
    name: str
    result: ToolResult


ToolEvent = Union[ToolCallStarted, ToolCallFinished]
ToolObserver = Callable[[ToolEvent], None]
