"""Agent orchestration layer: tool-schema generation + the agentic loop (RFC-0008).

The composition layer above providers/ and tools/. Owns the ToolInvocation -> ToolCall
mapping so providers/ stays free of a tools/ dependency. Pure library (no bootstrap/
config/api wiring this cycle — M8 Cycle 3 consumes it).

Stability: Experimental.
"""

from zygos.agent.config import ToolLoopConfig
from zygos.agent.loop import AgentResult, run_agentic_loop
from zygos.agent.schema import tool_schema

__all__ = ["ToolLoopConfig", "AgentResult", "run_agentic_loop", "tool_schema"]
