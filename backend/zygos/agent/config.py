"""ToolLoopConfig — bounds for the agentic loop (RFC-0008 §9).

Lives in agent/, NOT config/schema.py, this cycle (pure library; mirrors RetryPolicy
living in tools/). M8 Cycle 3 adds the bootstrap/ToolsConfig wiring.

Stability: Experimental.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolLoopConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_iterations: int = Field(default=8, ge=1)
    default_tool_choice: Literal["auto", "none", "required"] = "auto"
