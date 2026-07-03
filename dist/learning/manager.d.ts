import type { LearningConfig, LearningManagerMetrics, LearningProposal, LearningRuntimeDeps, ToolExecutionObservation } from '../types/learning.types.js';
import type { ToolCall, ToolResult } from '../types/tool.types.js';
interface LearningManagerDeps {
    config: LearningConfig;
    runtime: LearningRuntimeDeps;
    dbPath: string;
}
export declare class LearningManager {
    private readonly deps;
    private readonly store;
    private readonly modifier;
    private readonly creator;
    private cycleLock;
    constructor(deps: LearningManagerDeps);
    init(): Promise<void>;
    observeToolExecution(input: {
        sessionId: string;
        turnId: string;
        call: ToolCall;
        result: ToolResult;
        contextTags?: string[];
        contextSnapshot?: ToolExecutionObservation['contextSnapshot'];
    }): Promise<void>;
    runCycle(actor?: string): Promise<{
        proposals: LearningProposal[];
        applied: string[];
    }>;
    listProposals(status?: LearningProposal['status']): Promise<LearningProposal[]>;
    applyProposal(proposalId: string, approver?: string): Promise<void>;
    rollbackTool(toolName: string, targetVersionId?: number, actor?: string): Promise<void>;
    getMetrics(): Promise<LearningManagerMetrics>;
    close(): Promise<void>;
}
export {};
//# sourceMappingURL=manager.d.ts.map