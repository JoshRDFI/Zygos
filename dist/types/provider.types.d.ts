import type { ZygosError, ProviderRoute, UserTurnInput } from './core.types.js';
export type SupportedProviderKey = 'openai' | 'anthropic' | 'ollama' | 'vllm' | 'custom';
export type ProtocolType = 'openai_chat' | 'anthropic_messages';
export type ProtocolMessageRole = 'system' | 'user' | 'assistant' | 'tool';
export interface ProtocolMessage {
    role: ProtocolMessageRole;
    content: string;
    name?: string;
    toolCallId?: string;
}
export interface ModelRequest {
    sessionId: string;
    model: string;
    messages: ProtocolMessage[];
    temperature?: number;
    maxOutputTokens?: number;
    stream?: boolean;
    tools?: Array<Record<string, unknown>>;
    metadata?: Record<string, unknown>;
}
export interface ModelResponse {
    text: string;
    finishReason?: string;
    usage?: UsageStats;
    nativeResponse?: unknown;
}
export interface UsageStats {
    inputTokens?: number;
    outputTokens?: number;
    totalTokens?: number;
}
export interface ProviderConfig {
    enabled?: boolean;
    baseUrl?: string;
    apiKey?: string;
    organization?: string;
    timeoutMs?: number;
    headers?: Record<string, string>;
    models?: string[];
    protocol?: ProtocolType;
    weight?: number;
    requestSizeLimitBytes?: number;
    requireApiKey?: boolean;
}
export interface ProviderCapabilities {
    streaming: boolean;
    toolCalling: boolean;
    maxContextTokens: number;
    protocols: ProtocolType[];
}
export type ProviderStreamEvent = {
    type: 'delta';
    text: string;
} | {
    type: 'usage';
    usage: UsageStats;
} | {
    type: 'done';
    response: ModelResponse;
} | {
    type: 'error';
    error: ZygosError;
};
export interface Provider {
    readonly key: SupportedProviderKey;
    readonly capabilities: ProviderCapabilities;
    readonly config: ProviderConfig;
    supportsModel(model: string): boolean;
    estimateTokens(messages: ProtocolMessage[], model: string): TokenEstimate;
    complete(request: ModelRequest): Promise<ModelResponse>;
    stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void>;
}
export interface ProviderRegistry {
    get(provider: SupportedProviderKey): Provider | undefined;
    list(): Provider[];
}
export interface ProviderPlanningInput {
    userInput: UserTurnInput;
    routes: ProviderRoute[];
    tokenBudget?: TokenBudget;
}
export interface ProviderPlan {
    primary: ProviderRoute;
    fallbacks: ProviderRoute[];
}
export interface ProviderFailureContext {
    attemptedRoute: ProviderRoute;
    error: ZygosError;
    plan: ProviderPlan;
    attempt: number;
}
export interface RetryPolicy {
    maxAttempts: number;
    baseDelayMs: number;
    maxDelayMs: number;
    jitterRatio?: number;
}
export interface CircuitBreakerConfig {
    failureThreshold: number;
    resetTimeoutMs: number;
    halfOpenMaxRequests: number;
}
export interface RateLimitConfig {
    maxRequestsPerMinute: number;
    burst: number;
}
export interface ProviderObservabilityConfig {
    debug: boolean;
}
export interface FallbackChainConfig {
    retry: RetryPolicy;
    circuitBreaker: CircuitBreakerConfig;
    rateLimit: RateLimitConfig;
    observability: ProviderObservabilityConfig;
    gracefulDegradationMessage?: string;
    enableCredentialRotation?: boolean;
}
export interface ProviderRouteState {
    failures: number;
    openedAt?: number;
    halfOpenProbeCount?: number;
}
export interface TokenEstimate {
    promptTokens: number;
    maxOutputTokens: number;
    totalEstimate: number;
    modelContextWindow: number;
}
export interface TokenBudget {
    maxInputTokens: number;
    maxOutputTokens: number;
    maxTotalTokens: number;
}
export interface ContextWindowState {
    model: string;
    contextLimit: number;
    usedInputTokens: number;
    reservedOutputTokens: number;
    remainingTokens: number;
}
export interface OpenAIChatMessage {
    role: 'system' | 'user' | 'assistant' | 'tool';
    content: string;
    name?: string;
    tool_call_id?: string;
}
export interface OpenAIChatRequest {
    model: string;
    messages: OpenAIChatMessage[];
    temperature?: number;
    max_tokens?: number;
    stream?: boolean;
    tools?: Array<Record<string, unknown>>;
}
export interface AnthropicMessageBlock {
    type: 'text';
    text: string;
}
export interface AnthropicMessage {
    role: 'user' | 'assistant';
    content: AnthropicMessageBlock[];
}
export interface AnthropicMessagesRequest {
    model: string;
    max_tokens: number;
    messages: AnthropicMessage[];
    system?: string;
    temperature?: number;
    stream?: boolean;
    tools?: Array<Record<string, unknown>>;
}
//# sourceMappingURL=provider.types.d.ts.map