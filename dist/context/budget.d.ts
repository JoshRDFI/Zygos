import type { BudgetAllocationStrategy, ContextTurn, ContextWindow, TokenBudgetPlan, TokenBudgetReport, TurnTokenUsage } from '../types/context.types.js';
export interface TokenBudgetOptions {
    maxContextTokens: number;
    reserveOutputTokens?: number;
    reserveToolTokens?: number;
    thresholdRatio?: number;
    strategy?: BudgetAllocationStrategy;
}
export interface BudgetAllocation {
    inputTokens: number;
    retrievalTokens: number;
    historyTokens: number;
}
export declare class TokenBudgetSystem {
    private readonly history;
    plan(options: TokenBudgetOptions): TokenBudgetPlan;
    buildWindow(model: string, plan: TokenBudgetPlan, usedTokens: number, thresholdRatio?: number): ContextWindow;
    trackTurn(sessionId: string, usage: TurnTokenUsage): void;
    estimateTurns(turns: ContextTurn[]): number;
    estimateTurnTokens(turn: Pick<ContextTurn, 'content' | 'tokenUsage' | 'speaker'>): number;
    predictNextTurn(sessionId: string): number;
    enforceHardLimit(currentTokens: number, plan: TokenBudgetPlan): {
        allowed: boolean;
        reason?: string;
    };
    createReport(sessionId: string, turns: ContextTurn[], window: ContextWindow): TokenBudgetReport;
    private allocate;
}
//# sourceMappingURL=budget.d.ts.map