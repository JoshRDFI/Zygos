import type { ToolCall, ToolExecutionContext, ToolResult } from '../types/tool.types.js';
export interface ParallelExecutionNode {
    call: ToolCall;
    dependencies: string[];
    parallelSafe: boolean;
    resourceKey: string;
}
export interface ParallelExecutorOptions {
    concurrency: number;
}
export interface ParallelBatchOutcome {
    results: ToolResult[];
    failures: ToolResult[];
}
export type ToolCallRunner = (call: ToolCall, ctx: ToolExecutionContext) => Promise<ToolResult>;
export declare class ParallelExecutionOrchestrator {
    private readonly options;
    constructor(options?: ParallelExecutorOptions);
    execute(nodes: ParallelExecutionNode[], ctx: ToolExecutionContext, runOne: ToolCallRunner): Promise<ParallelBatchOutcome>;
}
//# sourceMappingURL=parallel-executor.d.ts.map