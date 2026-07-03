import type { CompactionResult, CompactionStrategy, ContextTurn } from '../types/context.types.js';
import { TokenBudgetSystem } from './budget.js';
export interface SummaryGenerator {
    summarize(input: {
        sessionId: string;
        turns: ContextTurn[];
        strategy: CompactionStrategy;
        targetTokens: number;
    }): Promise<string>;
}
export interface CompactionInput {
    sessionId: string;
    turns: ContextTurn[];
    maxTokens: number;
    strategy: CompactionStrategy;
}
export declare class HeuristicSummaryGenerator implements SummaryGenerator {
    summarize(input: {
        turns: ContextTurn[];
        strategy: CompactionStrategy;
    }): Promise<string>;
}
export declare class ContextCompactor {
    private readonly budget;
    private readonly summarizer;
    constructor(budget: TokenBudgetSystem, summarizer?: SummaryGenerator);
    compact(input: CompactionInput): Promise<CompactionResult>;
}
//# sourceMappingURL=compaction.d.ts.map