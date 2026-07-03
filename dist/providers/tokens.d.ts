import type { ContextWindowState, ProtocolMessage, Provider, TokenBudget, TokenEstimate } from '../types/provider.types.js';
/** Estimates request token usage and memoizes repeated estimations for identical inputs. */
export declare function estimateRequestTokens(provider: Provider, model: string, messages: ProtocolMessage[]): TokenEstimate;
/** Tracks context-window consumption for a request and reserved output budget. */
export declare function trackContextWindow(estimate: TokenEstimate, reservedOutputTokens: number, model: string): ContextWindowState;
/** Enforces a token budget policy against estimated token requirements. */
export declare function enforceTokenBudget(estimate: TokenEstimate, budget?: TokenBudget): {
    allowed: boolean;
    reason?: string;
};
//# sourceMappingURL=tokens.d.ts.map