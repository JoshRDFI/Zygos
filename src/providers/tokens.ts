import type {
  ContextWindowState,
  ProtocolMessage,
  Provider,
  TokenBudget,
  TokenEstimate
} from '../types/provider.types.js';

const estimateCache = new Map<string, TokenEstimate>();
const MAX_CACHE_SIZE = 1_000;

function cacheKey(provider: Provider, model: string, messages: ProtocolMessage[]): string {
  return `${provider.key}:${model}:${messages.map((m) => `${m.role}:${m.content}`).join('|')}`;
}

/** Estimates request token usage and memoizes repeated estimations for identical inputs. */
export function estimateRequestTokens(provider: Provider, model: string, messages: ProtocolMessage[]): TokenEstimate {
  const key = cacheKey(provider, model, messages);
  const cached = estimateCache.get(key);
  if (cached) {
    return cached;
  }

  const estimate = provider.estimateTokens(messages, model);
  if (estimateCache.size >= MAX_CACHE_SIZE) {
    const firstKey = estimateCache.keys().next().value;
    if (firstKey) {
      estimateCache.delete(firstKey);
    }
  }
  estimateCache.set(key, estimate);
  return estimate;
}

/** Tracks context-window consumption for a request and reserved output budget. */
export function trackContextWindow(
  estimate: TokenEstimate,
  reservedOutputTokens: number,
  model: string
): ContextWindowState {
  const remainingTokens = Math.max(0, estimate.modelContextWindow - estimate.promptTokens - reservedOutputTokens);

  return {
    model,
    contextLimit: estimate.modelContextWindow,
    usedInputTokens: estimate.promptTokens,
    reservedOutputTokens,
    remainingTokens
  };
}

/** Enforces a token budget policy against estimated token requirements. */
export function enforceTokenBudget(estimate: TokenEstimate, budget?: TokenBudget): {
  allowed: boolean;
  reason?: string;
} {
  if (!budget) {
    return { allowed: true };
  }

  if (estimate.promptTokens > budget.maxInputTokens) {
    return {
      allowed: false,
      reason: `Input token estimate ${estimate.promptTokens} exceeds budget ${budget.maxInputTokens}.`
    };
  }

  if (estimate.maxOutputTokens > budget.maxOutputTokens) {
    return {
      allowed: false,
      reason: `Output token reservation ${estimate.maxOutputTokens} exceeds budget ${budget.maxOutputTokens}.`
    };
  }

  if (estimate.totalEstimate > budget.maxTotalTokens) {
    return {
      allowed: false,
      reason: `Total token estimate ${estimate.totalEstimate} exceeds budget ${budget.maxTotalTokens}.`
    };
  }

  return { allowed: true };
}
