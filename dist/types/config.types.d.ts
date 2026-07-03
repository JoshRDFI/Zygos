import type { z } from 'zod';
import type { configSchema } from '../config/schema.js';
import type { ProtocolType } from './provider.types.js';
import type { RDTConfig } from './rdt.types.js';
import type { LearningConfig } from './learning.types.js';
import type { InterviewConfig } from './interviewer.types.js';
export interface RuntimeConfig {
    maxTurns: number;
    maxToolCallsPerTurn: number;
    enableStreamingTools: boolean;
}
export interface ProviderRouteConfig {
    provider: string;
    model: string;
    weight: number;
}
export interface RetryConfig {
    maxAttempts: number;
    baseDelayMs: number;
    maxDelayMs: number;
    jitterRatio: number;
}
export interface CircuitBreakerRuntimeConfig {
    failureThreshold: number;
    resetTimeoutMs: number;
    halfOpenMaxRequests: number;
}
export interface RateLimitRuntimeConfig {
    maxRequestsPerMinute: number;
    burst: number;
}
export interface ProviderObservabilityRuntimeConfig {
    debug: boolean;
}
export interface ProviderCredentialConfig {
    apiKey?: string;
    baseUrl?: string;
    organization?: string;
    protocol?: ProtocolType;
    timeoutMs?: number;
    enabled?: boolean;
    models?: string[];
    headers?: Record<string, string>;
    weight?: number;
    requestSizeLimitBytes?: number;
    requireApiKey?: boolean;
}
export interface ProvidersConfig {
    primary: ProviderRouteConfig;
    fallbacks: ProviderRouteConfig[];
    retry: RetryConfig;
    circuitBreaker: CircuitBreakerRuntimeConfig;
    rateLimit: RateLimitRuntimeConfig;
    observability: ProviderObservabilityRuntimeConfig;
    gracefulDegradationMessage?: string;
    credentials: {
        openai?: ProviderCredentialConfig;
        anthropic?: ProviderCredentialConfig;
        ollama?: ProviderCredentialConfig;
        vllm?: ProviderCredentialConfig;
        custom?: ProviderCredentialConfig;
    };
}
export interface ZygosConfig {
    runtime: RuntimeConfig;
    providers: ProvidersConfig;
    rdt: RDTConfig;
    learning: LearningConfig;
    interview: InterviewConfig;
}
export type ZygosConfigSchema = z.infer<typeof configSchema>;
//# sourceMappingURL=config.types.d.ts.map