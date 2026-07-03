import { PermissionManager } from './permissions.js';
import { type ToolCall, type ToolExecutionContext, type ToolExecutionEvent, type ToolRegistry, type ToolResult } from '../types/tool.types.js';
export interface StreamingExecutorOptions {
    concurrency?: number;
    defaultTimeoutMs?: number;
    progressChunkSize?: number;
}
export declare class StreamingToolExecutor {
    private readonly registry;
    private readonly logger;
    private readonly permissions;
    private readonly orchestrator;
    private readonly metrics;
    private readonly options;
    constructor(registry: ToolRegistry, opts?: StreamingExecutorOptions, permissions?: PermissionManager);
    getMetrics(): Record<string, {
        started: number;
        succeeded: number;
        failed: number;
        avgDurationMs: number;
    }>;
    execute(call: ToolCall, ctx: ToolExecutionContext): Promise<ToolResult>;
    executeBatch(calls: ToolCall[], ctx: ToolExecutionContext): Promise<ToolResult[]>;
    executeBatchStream(calls: ToolCall[], ctx: ToolExecutionContext): AsyncGenerator<ToolExecutionEvent, ToolResult[], void>;
    private executeOneStream;
    private isTransientError;
}
//# sourceMappingURL=streaming-executor.d.ts.map