import type { HarnessConfig } from './config.types.js';
import type { ProviderPlan } from './provider.types.js';
import type { ToolCall, ToolExecutionContext, ToolExecutionEvent, ToolProgressEvent, ToolResult } from './tool.types.js';
import type { ContextManagerLike, SearchQuery, SearchResult } from './context.types.js';
import type { RDTProgressEvent, RDTRuntimeInput } from './rdt.types.js';
import type { LearningManager } from '../learning/manager.js';
import type { LearningManagerMetrics, LearningProposal, LearningProposalStatus } from './learning.types.js';
import type { BuildPlan, BuildPlanExport, InterviewManagerLike, InterviewMetrics, InterviewResponse } from './interviewer.types.js';
export type QueryState = 'IDLE' | 'PREPARE_CONTEXT' | 'PLAN_PROVIDER' | 'MODEL_STREAMING' | 'TOOL_CALLS_PENDING' | 'TOOL_EXECUTING' | 'RDT_OPTIONAL' | 'FINALIZE' | 'PERSIST' | 'FAILED_TERMINAL';
export type LifecyclePhase = 'startup' | 'turn' | 'shutdown';
export type ProviderKey = 'anthropic' | 'openai' | 'ollama' | 'vllm' | 'custom';
export interface UserTurnInput {
    sessionId: string;
    userMessage: string;
    mode?: 'standard' | 'interview' | 'batch';
    interview?: {
        action?: 'start' | 'answer' | 'complete' | 'status' | 'plan_export';
        stakeholderId?: string;
        overrideGating?: boolean;
    };
}
export interface ProviderRoute {
    provider: ProviderKey;
    model: string;
    reason: string;
}
export interface QuerySessionState {
    sessionId: string;
    turnId: string;
    state: QueryState;
    iteration: number;
    activeProvider: ProviderRoute;
    providerPlan?: ProviderPlan;
    fallbackDepth: number;
    messages: string[];
    pendingTools: ToolCall[];
    outputBuffer: string;
    startedAt: number;
    updatedAt: number;
    lastError?: HarnessError;
}
export interface TurnResult {
    sessionId: string;
    turnId: string;
    finalText: string;
    tools: ToolResult[];
    state: Extract<QueryState, 'IDLE' | 'FAILED_TERMINAL'>;
    usage: {
        inputChars: number;
        outputChars: number;
    };
    interview?: {
        response: InterviewResponse;
        plan?: BuildPlan;
        planExport?: BuildPlanExport;
    };
    rdt?: {
        enabled: boolean;
        loopsUsed: number;
        haltedEarly: boolean;
        finalConfidence: number;
        quality: {
            avgCoherence: number;
            avgCompleteness: number;
            avgConsistency: number;
            avgAggregate: number;
        };
    };
}
export interface HarnessError {
    code: 'recoverable_provider_error' | 'network_timeout' | 'malformed_response' | 'rate_limited' | 'authentication_error' | 'provider_unavailable' | 'tool_contract_error' | 'permission_denied' | 'budget_exhausted' | 'fatal_runtime_error';
    message: string;
    details?: Record<string, unknown>;
}
export type EngineEvent = {
    type: 'state_changed';
    from: QueryState;
    to: QueryState;
} | {
    type: 'provider_selected';
    route: ProviderRoute;
} | {
    type: 'retry_scheduled';
    delayMs: number;
    reason: string;
} | {
    type: 'fallback_activated';
    route: ProviderRoute;
} | {
    type: 'model_delta';
    text: string;
} | {
    type: 'rdt_progress';
    event: RDTProgressEvent;
} | {
    type: 'rdt_observability';
    metrics: {
        loopsUsed: number;
        haltedEarly: boolean;
        finalConfidence: number;
        avgAggregateQuality: number;
    };
} | {
    type: 'tool_started';
    call: ToolCall;
} | {
    type: 'tool_progress';
    event: ToolProgressEvent;
} | {
    type: 'tool_timeout';
    call: ToolCall;
    elapsedMs: number;
} | {
    type: 'tool_completed';
    result: ToolResult;
} | {
    type: 'tool_batch_completed';
    results: ToolResult[];
} | {
    type: 'learning_cycle';
    proposals: number;
    applied: number;
} | {
    type: 'learning_applied';
    proposalId: string;
    kind: 'modification' | 'creation';
} | {
    type: 'interview_progress';
    response: InterviewResponse;
} | {
    type: 'interview_plan_generated';
    planId: string;
    complexity: 'low' | 'medium' | 'high';
    estimatedEffortHours: number;
} | {
    type: 'interview_metrics';
    metrics: InterviewMetrics;
} | {
    type: 'turn_completed';
    result: TurnResult;
} | {
    type: 'turn_failed';
    error: HarnessError;
};
export interface StateStore {
    saveSession(session: QuerySessionState): Promise<void>;
    getSession(sessionId: string): Promise<QuerySessionState | null>;
    appendEvent(sessionId: string, event: EngineEvent): Promise<void>;
    getEvents(sessionId: string): Promise<EngineEvent[]>;
    abortSession(sessionId: string): Promise<void>;
}
export interface QueryEngine {
    runTurn(input: UserTurnInput): AsyncGenerator<EngineEvent, TurnResult, void>;
    getState(sessionId: string): Promise<QuerySessionState | null>;
    abort(sessionId: string): Promise<void>;
    searchHistory?(query: SearchQuery): Promise<SearchResult[]>;
    listLearningProposals?(status?: LearningProposalStatus): Promise<LearningProposal[]>;
    applyLearningProposal?(proposalId: string, approver?: string): Promise<void>;
    rollbackLearnedTool?(toolName: string, targetVersionId?: number, actor?: string): Promise<void>;
    getLearningMetrics?(): Promise<LearningManagerMetrics>;
    getInterviewSession?(sessionId: string): Promise<InterviewResponse | null>;
    getInterviewPlan?(sessionId: string): Promise<BuildPlan | null>;
    exportInterviewPlan?(sessionId: string): Promise<BuildPlanExport | null>;
}
export interface ToolExecutorLike {
    executeBatch(calls: ToolCall[], ctx: ToolExecutionContext): Promise<ToolResult[]>;
    executeBatchStream?(calls: ToolCall[], ctx: ToolExecutionContext): AsyncGenerator<ToolExecutionEvent, ToolResult[], void>;
    getMetrics?(): Record<string, {
        started: number;
        succeeded: number;
        failed: number;
        avgDurationMs: number;
    }>;
}
export interface QueryEngineDeps {
    config: HarnessConfig;
    stateStore: StateStore;
    toolExecutor: ToolExecutorLike;
    contextManager?: ContextManagerLike;
    learningManager?: LearningManager;
    interviewer?: InterviewManagerLike;
    pickProviderPlan(input: UserTurnInput): Promise<ProviderPlan>;
    executeModel(input: UserTurnInput, session: QuerySessionState, emitMeta: (event: Extract<EngineEvent, {
        type: 'provider_selected' | 'retry_scheduled' | 'fallback_activated';
    }>) => Promise<void>): AsyncGenerator<string, string, void>;
    runRdt?(input: RDTRuntimeInput, session: QuerySessionState, emitProgress: (event: RDTProgressEvent) => Promise<void>): Promise<{
        finalText: string;
        loopsUsed: number;
        haltedEarly: boolean;
        finalConfidence: number;
        quality: {
            avgCoherence: number;
            avgCompleteness: number;
            avgConsistency: number;
            avgAggregate: number;
        };
    }>;
}
//# sourceMappingURL=core.types.d.ts.map