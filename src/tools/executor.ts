import type { ToolCall, ToolExecutionContext, ToolRegistry, ToolResult } from '../types/tool.types.js';
import { StreamingToolExecutor, type StreamingExecutorOptions } from './streaming-executor.js';

/**
 * Backward-compatible executor facade.
 * Phase 3 uses StreamingToolExecutor under the hood while preserving execute/executeBatch signatures.
 */
export class ToolExecutor {
  private readonly delegate: StreamingToolExecutor;

  constructor(registry: ToolRegistry, options: StreamingExecutorOptions = {}) {
    this.delegate = new StreamingToolExecutor(registry, options);
  }

  async execute(call: ToolCall, ctx: ToolExecutionContext): Promise<ToolResult> {
    return this.delegate.execute(call, ctx);
  }

  async executeBatch(calls: ToolCall[], ctx: ToolExecutionContext): Promise<ToolResult[]> {
    return this.delegate.executeBatch(calls, ctx);
  }

  executeBatchStream(calls: ToolCall[], ctx: ToolExecutionContext) {
    return this.delegate.executeBatchStream(calls, ctx);
  }

  getMetrics() {
    return this.delegate.getMetrics();
  }
}
