import type { EngineEvent, QueryEngine, QueryEngineDeps, QuerySessionState, TurnResult, UserTurnInput } from '../types/core.types.js';
export declare class QueryEngineImpl implements QueryEngine {
    private readonly deps;
    constructor(deps: QueryEngineDeps);
    runTurn(input: UserTurnInput): AsyncGenerator<EngineEvent, TurnResult, void>;
    getState(sessionId: string): Promise<QuerySessionState | null>;
    abort(sessionId: string): Promise<void>;
    searchHistory(query: import('../types/context.types.js').SearchQuery): Promise<import("../types/context.types.js").SearchResult[]>;
    listLearningProposals(status?: 'proposed' | 'approved' | 'rejected' | 'applied' | 'rolled_back'): Promise<import("../index.js").LearningProposal[]>;
    applyLearningProposal(proposalId: string, approver?: string): Promise<void>;
    rollbackLearnedTool(toolName: string, targetVersionId?: number, actor?: string): Promise<void>;
    getLearningMetrics(): Promise<import("../index.js").LearningManagerMetrics>;
    getInterviewSession(sessionId: string): Promise<{
        session: import("../index.js").InterviewSession;
        done: boolean;
    } | null>;
    getInterviewPlan(sessionId: string): Promise<import("../index.js").BuildPlan | null>;
    exportInterviewPlan(sessionId: string): Promise<import("../index.js").BuildPlanExport | null>;
    private transition;
    private emit;
    private error;
    private normalizeError;
}
//# sourceMappingURL=engine.d.ts.map