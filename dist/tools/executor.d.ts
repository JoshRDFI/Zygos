import type { ToolCall, ToolExecutionContext, ToolRegistry, ToolResult } from '../types/tool.types.js';
import { type StreamingExecutorOptions } from './streaming-executor.js';
/**
 * Backward-compatible executor facade.
 * Phase 3 uses StreamingToolExecutor under the hood while preserving execute/executeBatch signatures.
 */
export declare class ToolExecutor {
    private readonly delegate;
    constructor(registry: ToolRegistry, options?: StreamingExecutorOptions);
    execute(call: ToolCall, ctx: ToolExecutionContext): Promise<ToolResult>;
    executeBatch(calls: ToolCall[], ctx: ToolExecutionContext): Promise<ToolResult[]>;
    executeBatchStream(calls: ToolCall[], ctx: ToolExecutionContext): AsyncGenerator<{
        type: "tool_started";
        call: {
            name: string;
            id: string;
            input: Record<string, unknown>;
        };
    } | {
        type: "tool_progress";
        event: {
            toolCallId: string;
            timestamp: number;
            message?: string | undefined;
            progress?: number | undefined;
            chunk?: unknown;
        };
    } | {
        type: "tool_completed";
        result: {
            toolCallId: string;
            ok: boolean;
            durationMs: number;
            synthetic: boolean;
            partial: boolean;
            warnings: string[];
            output?: unknown;
            error?: string | undefined;
            normalizedError?: {
                code: string;
                message: string;
                retryable: boolean;
                details?: Record<string, unknown> | undefined;
            } | undefined;
            bytes?: number | undefined;
        };
    }, {
        toolCallId: string;
        ok: boolean;
        durationMs: number;
        synthetic: boolean;
        partial: boolean;
        warnings: string[];
        output?: unknown;
        error?: string | undefined;
        normalizedError?: {
            code: string;
            message: string;
            retryable: boolean;
            details?: Record<string, unknown> | undefined;
        } | undefined;
        bytes?: number | undefined;
    }[], void>;
    getMetrics(): Record<string, {
        started: number;
        succeeded: number;
        failed: number;
        avgDurationMs: number;
    }>;
}
//# sourceMappingURL=executor.d.ts.map