import type { ProviderRoute, TurnResult, UserTurnInput } from './core.types.js';
export type ContextSpeaker = 'system' | 'user' | 'assistant' | 'tool' | 'summary';
export type ContextContentType = 'message' | 'tool_call' | 'tool_result' | 'summary' | 'memory';
export type BudgetAllocationStrategy = 'equal' | 'priority_based';
export type CompactionStrategyType = 'sliding_summary' | 'hierarchical' | 'aggressive';
export interface TurnTokenUsage {
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
    estimated?: boolean;
}
export interface ContextTurn {
    id: string;
    sessionId: string;
    turnId?: string;
    turnIndex: number;
    speaker: ContextSpeaker;
    contentType: ContextContentType;
    content: string;
    toolName?: string;
    model?: string;
    provider?: string;
    createdAt: number;
    updatedAt: number;
    tokenUsage?: TurnTokenUsage;
    importanceScore: number;
    tags: string[];
    metadata?: Record<string, unknown>;
    summaryOfTurnIds?: string[];
    piiDetected?: boolean;
    isCompacted?: boolean;
}
export interface ContextWindow {
    model: string;
    maxTokens: number;
    reservedOutputTokens: number;
    reservedToolTokens: number;
    usedTokens: number;
    remainingTokens: number;
    thresholdRatio: number;
}
export interface TokenBudgetPlan {
    strategy: BudgetAllocationStrategy;
    hardLimitTokens: number;
    reservedOutputTokens: number;
    reservedToolTokens: number;
    availableForHistoryTokens: number;
    availableForRetrievalTokens: number;
    availableForInputTokens: number;
}
export interface TokenBudgetReport {
    sessionId: string;
    turnId?: string;
    generatedAt: number;
    usedInputTokens: number;
    usedOutputTokens: number;
    projectedNextTurnTokens: number;
    remainingTokens: number;
    overflowRisk: 'low' | 'medium' | 'high';
    bySpeaker: Record<ContextSpeaker, number>;
}
export interface CompactionStrategy {
    type: CompactionStrategyType;
    targetReductionRatio: number;
    preserveToolPairs: boolean;
    preserveTaggedTurns: boolean;
    preserveRecentTurns: number;
    maxSummaryTokens: number;
}
export interface CompactionResult {
    compacted: boolean;
    summaryTurn?: ContextTurn;
    removedTurnIds: string[];
    preservedTurnIds: string[];
    tokenDelta: number;
    warning?: string;
}
export interface SearchQuery {
    sessionId?: string;
    query: string;
    speaker?: ContextSpeaker;
    contentType?: ContextContentType;
    fromTs?: number;
    toTs?: number;
    limit?: number;
    offset?: number;
    includeSnippets?: boolean;
}
export interface SearchResult {
    turn: ContextTurn;
    rank: number;
    snippet?: string;
    highlights?: string[];
}
export interface MemoryFact {
    id: string;
    sessionId: string;
    fact: string;
    confidence: number;
    sourceTurnId: string;
    createdAt: number;
    tags: string[];
}
export interface MemoryRetrieval {
    query: string;
    results: SearchResult[];
    facts: MemoryFact[];
    generatedAt: number;
}
export interface ContextSnapshot {
    sessionId: string;
    turns: ContextTurn[];
    memory: MemoryFact[];
    window: ContextWindow;
    budget: TokenBudgetReport;
    createdAt: number;
}
export interface ContextPreparationResult {
    input: UserTurnInput;
    selectedTurns: ContextTurn[];
    memory: MemoryRetrieval;
    window: ContextWindow;
    budgetPlan: TokenBudgetPlan;
    budgetReport: TokenBudgetReport;
    compacted: boolean;
    warnings: string[];
}
export interface ContextPostTurnInput {
    sessionId: string;
    turnId: string;
    inputMessage: string;
    assistantMessage: string;
    toolMessages?: string[];
    providerRoute?: ProviderRoute;
    result: TurnResult;
    startedAt: number;
    completedAt: number;
}
export interface ContextManagerLike {
    prepare(input: UserTurnInput, model?: string): Promise<ContextPreparationResult>;
    postTurnUpdate(input: ContextPostTurnInput): Promise<void>;
    getSnapshot(sessionId: string, model?: string): Promise<ContextSnapshot | null>;
    search(query: SearchQuery): Promise<SearchResult[]>;
}
//# sourceMappingURL=context.types.d.ts.map