import { z } from 'zod';
export declare const providerRouteSchema: z.ZodObject<{
    provider: z.ZodEnum<["openai", "anthropic", "ollama", "vllm", "custom"]>;
    model: z.ZodString;
    weight: z.ZodDefault<z.ZodNumber>;
}, "strip", z.ZodTypeAny, {
    provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
    model: string;
    weight: number;
}, {
    provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
    model: string;
    weight?: number | undefined;
}>;
export declare const providerCredentialSchema: z.ZodObject<{
    apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
    baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
    organization: z.ZodOptional<z.ZodString>;
    protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
    timeoutMs: z.ZodOptional<z.ZodNumber>;
    enabled: z.ZodDefault<z.ZodBoolean>;
    models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
    headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
    weight: z.ZodDefault<z.ZodNumber>;
    requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
    requireApiKey: z.ZodOptional<z.ZodBoolean>;
}, "strip", z.ZodTypeAny, {
    weight: number;
    enabled: boolean;
    models: string[];
    headers: Record<string, string>;
    requestSizeLimitBytes: number;
    apiKey?: string | undefined;
    baseUrl?: string | undefined;
    organization?: string | undefined;
    protocol?: "openai_chat" | "anthropic_messages" | undefined;
    timeoutMs?: number | undefined;
    requireApiKey?: boolean | undefined;
}, {
    weight?: number | undefined;
    apiKey?: string | undefined;
    baseUrl?: string | undefined;
    organization?: string | undefined;
    protocol?: "openai_chat" | "anthropic_messages" | undefined;
    timeoutMs?: number | undefined;
    enabled?: boolean | undefined;
    models?: string[] | undefined;
    headers?: Record<string, string> | undefined;
    requestSizeLimitBytes?: number | undefined;
    requireApiKey?: boolean | undefined;
}>;
export declare const configSchema: z.ZodObject<{
    runtime: z.ZodObject<{
        maxTurns: z.ZodDefault<z.ZodNumber>;
        maxToolCallsPerTurn: z.ZodDefault<z.ZodNumber>;
        enableStreamingTools: z.ZodDefault<z.ZodBoolean>;
    }, "strip", z.ZodTypeAny, {
        maxTurns: number;
        maxToolCallsPerTurn: number;
        enableStreamingTools: boolean;
    }, {
        maxTurns?: number | undefined;
        maxToolCallsPerTurn?: number | undefined;
        enableStreamingTools?: boolean | undefined;
    }>;
    providers: z.ZodEffects<z.ZodObject<{
        primary: z.ZodObject<{
            provider: z.ZodEnum<["openai", "anthropic", "ollama", "vllm", "custom"]>;
            model: z.ZodString;
            weight: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        }, {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        }>;
        fallbacks: z.ZodDefault<z.ZodArray<z.ZodObject<{
            provider: z.ZodEnum<["openai", "anthropic", "ollama", "vllm", "custom"]>;
            model: z.ZodString;
            weight: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        }, {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        }>, "many">>;
        retry: z.ZodEffects<z.ZodObject<{
            maxAttempts: z.ZodDefault<z.ZodNumber>;
            baseDelayMs: z.ZodDefault<z.ZodNumber>;
            maxDelayMs: z.ZodDefault<z.ZodNumber>;
            jitterRatio: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            maxAttempts: number;
            baseDelayMs: number;
            maxDelayMs: number;
            jitterRatio: number;
        }, {
            maxAttempts?: number | undefined;
            baseDelayMs?: number | undefined;
            maxDelayMs?: number | undefined;
            jitterRatio?: number | undefined;
        }>, {
            maxAttempts: number;
            baseDelayMs: number;
            maxDelayMs: number;
            jitterRatio: number;
        }, {
            maxAttempts?: number | undefined;
            baseDelayMs?: number | undefined;
            maxDelayMs?: number | undefined;
            jitterRatio?: number | undefined;
        }>;
        circuitBreaker: z.ZodObject<{
            failureThreshold: z.ZodDefault<z.ZodNumber>;
            resetTimeoutMs: z.ZodDefault<z.ZodNumber>;
            halfOpenMaxRequests: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            failureThreshold: number;
            resetTimeoutMs: number;
            halfOpenMaxRequests: number;
        }, {
            failureThreshold?: number | undefined;
            resetTimeoutMs?: number | undefined;
            halfOpenMaxRequests?: number | undefined;
        }>;
        rateLimit: z.ZodObject<{
            maxRequestsPerMinute: z.ZodDefault<z.ZodNumber>;
            burst: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            maxRequestsPerMinute: number;
            burst: number;
        }, {
            maxRequestsPerMinute?: number | undefined;
            burst?: number | undefined;
        }>;
        observability: z.ZodObject<{
            debug: z.ZodDefault<z.ZodBoolean>;
        }, "strip", z.ZodTypeAny, {
            debug: boolean;
        }, {
            debug?: boolean | undefined;
        }>;
        gracefulDegradationMessage: z.ZodOptional<z.ZodString>;
        credentials: z.ZodObject<{
            openai: z.ZodOptional<z.ZodObject<{
                apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
                baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
                organization: z.ZodOptional<z.ZodString>;
                protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
                timeoutMs: z.ZodOptional<z.ZodNumber>;
                enabled: z.ZodDefault<z.ZodBoolean>;
                models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
                weight: z.ZodDefault<z.ZodNumber>;
                requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
                requireApiKey: z.ZodOptional<z.ZodBoolean>;
            }, "strip", z.ZodTypeAny, {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            }, {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            }>>;
            anthropic: z.ZodOptional<z.ZodObject<{
                apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
                baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
                organization: z.ZodOptional<z.ZodString>;
                protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
                timeoutMs: z.ZodOptional<z.ZodNumber>;
                enabled: z.ZodDefault<z.ZodBoolean>;
                models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
                weight: z.ZodDefault<z.ZodNumber>;
                requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
                requireApiKey: z.ZodOptional<z.ZodBoolean>;
            }, "strip", z.ZodTypeAny, {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            }, {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            }>>;
            ollama: z.ZodOptional<z.ZodObject<{
                apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
                baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
                organization: z.ZodOptional<z.ZodString>;
                protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
                timeoutMs: z.ZodOptional<z.ZodNumber>;
                enabled: z.ZodDefault<z.ZodBoolean>;
                models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
                weight: z.ZodDefault<z.ZodNumber>;
                requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
                requireApiKey: z.ZodOptional<z.ZodBoolean>;
            }, "strip", z.ZodTypeAny, {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            }, {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            }>>;
            vllm: z.ZodOptional<z.ZodObject<{
                apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
                baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
                organization: z.ZodOptional<z.ZodString>;
                protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
                timeoutMs: z.ZodOptional<z.ZodNumber>;
                enabled: z.ZodDefault<z.ZodBoolean>;
                models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
                weight: z.ZodDefault<z.ZodNumber>;
                requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
                requireApiKey: z.ZodOptional<z.ZodBoolean>;
            }, "strip", z.ZodTypeAny, {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            }, {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            }>>;
            custom: z.ZodOptional<z.ZodObject<{
                apiKey: z.ZodOptional<z.ZodUnion<[z.ZodString, z.ZodString]>>;
                baseUrl: z.ZodOptional<z.ZodEffects<z.ZodString, string, string>>;
                organization: z.ZodOptional<z.ZodString>;
                protocol: z.ZodOptional<z.ZodEnum<["openai_chat", "anthropic_messages"]>>;
                timeoutMs: z.ZodOptional<z.ZodNumber>;
                enabled: z.ZodDefault<z.ZodBoolean>;
                models: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                headers: z.ZodDefault<z.ZodRecord<z.ZodString, z.ZodString>>;
                weight: z.ZodDefault<z.ZodNumber>;
                requestSizeLimitBytes: z.ZodDefault<z.ZodNumber>;
                requireApiKey: z.ZodOptional<z.ZodBoolean>;
            }, "strip", z.ZodTypeAny, {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            }, {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            }>>;
        }, "strip", z.ZodTypeAny, {
            openai?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        }, {
            openai?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        }>;
    }, "strip", z.ZodTypeAny, {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        };
        fallbacks: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        }[];
        retry: {
            maxAttempts: number;
            baseDelayMs: number;
            maxDelayMs: number;
            jitterRatio: number;
        };
        circuitBreaker: {
            failureThreshold: number;
            resetTimeoutMs: number;
            halfOpenMaxRequests: number;
        };
        rateLimit: {
            maxRequestsPerMinute: number;
            burst: number;
        };
        observability: {
            debug: boolean;
        };
        credentials: {
            openai?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        gracefulDegradationMessage?: string | undefined;
    }, {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        };
        retry: {
            maxAttempts?: number | undefined;
            baseDelayMs?: number | undefined;
            maxDelayMs?: number | undefined;
            jitterRatio?: number | undefined;
        };
        circuitBreaker: {
            failureThreshold?: number | undefined;
            resetTimeoutMs?: number | undefined;
            halfOpenMaxRequests?: number | undefined;
        };
        rateLimit: {
            maxRequestsPerMinute?: number | undefined;
            burst?: number | undefined;
        };
        observability: {
            debug?: boolean | undefined;
        };
        credentials: {
            openai?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        fallbacks?: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        }[] | undefined;
        gracefulDegradationMessage?: string | undefined;
    }>, {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        };
        fallbacks: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        }[];
        retry: {
            maxAttempts: number;
            baseDelayMs: number;
            maxDelayMs: number;
            jitterRatio: number;
        };
        circuitBreaker: {
            failureThreshold: number;
            resetTimeoutMs: number;
            halfOpenMaxRequests: number;
        };
        rateLimit: {
            maxRequestsPerMinute: number;
            burst: number;
        };
        observability: {
            debug: boolean;
        };
        credentials: {
            openai?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        gracefulDegradationMessage?: string | undefined;
    }, {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        };
        retry: {
            maxAttempts?: number | undefined;
            baseDelayMs?: number | undefined;
            maxDelayMs?: number | undefined;
            jitterRatio?: number | undefined;
        };
        circuitBreaker: {
            failureThreshold?: number | undefined;
            resetTimeoutMs?: number | undefined;
            halfOpenMaxRequests?: number | undefined;
        };
        rateLimit: {
            maxRequestsPerMinute?: number | undefined;
            burst?: number | undefined;
        };
        observability: {
            debug?: boolean | undefined;
        };
        credentials: {
            openai?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        fallbacks?: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        }[] | undefined;
        gracefulDegradationMessage?: string | undefined;
    }>;
    rdt: z.ZodEffects<z.ZodObject<{
        enabled: z.ZodDefault<z.ZodBoolean>;
        profile: z.ZodDefault<z.ZodEnum<["shallow", "balanced", "deep"]>>;
        prelude: z.ZodDefault<z.ZodObject<{
            enabled: z.ZodDefault<z.ZodBoolean>;
            temperature: z.ZodDefault<z.ZodNumber>;
            maxTokens: z.ZodOptional<z.ZodNumber>;
            systemInstruction: z.ZodString;
        }, "strip", z.ZodTypeAny, {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        }, {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        }>>;
        recurrent: z.ZodDefault<z.ZodObject<{
            enabled: z.ZodDefault<z.ZodBoolean>;
            temperature: z.ZodDefault<z.ZodNumber>;
            maxTokens: z.ZodOptional<z.ZodNumber>;
            systemInstruction: z.ZodString;
        } & {
            minLoopIters: z.ZodDefault<z.ZodNumber>;
            maxLoopIters: z.ZodDefault<z.ZodNumber>;
            allowBacktracking: z.ZodDefault<z.ZodBoolean>;
            allowParallelPaths: z.ZodDefault<z.ZodBoolean>;
        }, "strip", z.ZodTypeAny, {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            minLoopIters: number;
            maxLoopIters: number;
            allowBacktracking: boolean;
            allowParallelPaths: boolean;
            maxTokens?: number | undefined;
        }, {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            allowBacktracking?: boolean | undefined;
            allowParallelPaths?: boolean | undefined;
        }>>;
        coda: z.ZodDefault<z.ZodObject<{
            enabled: z.ZodDefault<z.ZodBoolean>;
            temperature: z.ZodDefault<z.ZodNumber>;
            maxTokens: z.ZodOptional<z.ZodNumber>;
            systemInstruction: z.ZodString;
        }, "strip", z.ZodTypeAny, {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        }, {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        }>>;
        loop: z.ZodObject<{
            maxLoopIters: z.ZodDefault<z.ZodNumber>;
            minLoopIters: z.ZodDefault<z.ZodNumber>;
            maxRevisionDepth: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            minLoopIters: number;
            maxLoopIters: number;
            maxRevisionDepth: number;
        }, {
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            maxRevisionDepth?: number | undefined;
        }>;
        confidence: z.ZodObject<{
            thresholds: z.ZodObject<{
                earlyExit: z.ZodDefault<z.ZodNumber>;
                revise: z.ZodDefault<z.ZodNumber>;
                floor: z.ZodDefault<z.ZodNumber>;
            }, "strip", z.ZodTypeAny, {
                earlyExit: number;
                revise: number;
                floor: number;
            }, {
                earlyExit?: number | undefined;
                revise?: number | undefined;
                floor?: number | undefined;
            }>;
            adaptive: z.ZodDefault<z.ZodBoolean>;
            adaptUpDelta: z.ZodDefault<z.ZodNumber>;
            adaptDownDelta: z.ZodDefault<z.ZodNumber>;
            smoothingFactor: z.ZodDefault<z.ZodNumber>;
        }, "strip", z.ZodTypeAny, {
            thresholds: {
                earlyExit: number;
                revise: number;
                floor: number;
            };
            adaptive: boolean;
            adaptUpDelta: number;
            adaptDownDelta: number;
            smoothingFactor: number;
        }, {
            thresholds: {
                earlyExit?: number | undefined;
                revise?: number | undefined;
                floor?: number | undefined;
            };
            adaptive?: boolean | undefined;
            adaptUpDelta?: number | undefined;
            adaptDownDelta?: number | undefined;
            smoothingFactor?: number | undefined;
        }>;
        attention: z.ZodObject<{
            defaultMode: z.ZodDefault<z.ZodEnum<["mla", "gqa", "auto"]>>;
            switchByTask: z.ZodDefault<z.ZodBoolean>;
            modeSwitchComplexityThreshold: z.ZodDefault<z.ZodNumber>;
            moe: z.ZodObject<{
                enabled: z.ZodDefault<z.ZodBoolean>;
                routedExperts: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                sharedExperts: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
                topK: z.ZodDefault<z.ZodNumber>;
                maxParallelExperts: z.ZodDefault<z.ZodNumber>;
                loadBalanceWindow: z.ZodDefault<z.ZodNumber>;
            }, "strip", z.ZodTypeAny, {
                enabled: boolean;
                routedExperts: string[];
                sharedExperts: string[];
                topK: number;
                maxParallelExperts: number;
                loadBalanceWindow: number;
            }, {
                enabled?: boolean | undefined;
                routedExperts?: string[] | undefined;
                sharedExperts?: string[] | undefined;
                topK?: number | undefined;
                maxParallelExperts?: number | undefined;
                loadBalanceWindow?: number | undefined;
            }>;
        }, "strip", z.ZodTypeAny, {
            defaultMode: "mla" | "gqa" | "auto";
            switchByTask: boolean;
            modeSwitchComplexityThreshold: number;
            moe: {
                enabled: boolean;
                routedExperts: string[];
                sharedExperts: string[];
                topK: number;
                maxParallelExperts: number;
                loadBalanceWindow: number;
            };
        }, {
            moe: {
                enabled?: boolean | undefined;
                routedExperts?: string[] | undefined;
                sharedExperts?: string[] | undefined;
                topK?: number | undefined;
                maxParallelExperts?: number | undefined;
                loadBalanceWindow?: number | undefined;
            };
            defaultMode?: "mla" | "gqa" | "auto" | undefined;
            switchByTask?: boolean | undefined;
            modeSwitchComplexityThreshold?: number | undefined;
        }>;
        quality: z.ZodObject<{
            enableTraceLogging: z.ZodDefault<z.ZodBoolean>;
            preserveReasoningChain: z.ZodDefault<z.ZodBoolean>;
            computeAdaptive: z.ZodDefault<z.ZodBoolean>;
            enableMultiHop: z.ZodDefault<z.ZodBoolean>;
        }, "strip", z.ZodTypeAny, {
            enableTraceLogging: boolean;
            preserveReasoningChain: boolean;
            computeAdaptive: boolean;
            enableMultiHop: boolean;
        }, {
            enableTraceLogging?: boolean | undefined;
            preserveReasoningChain?: boolean | undefined;
            computeAdaptive?: boolean | undefined;
            enableMultiHop?: boolean | undefined;
        }>;
    }, "strip", z.ZodTypeAny, {
        enabled: boolean;
        profile: "shallow" | "balanced" | "deep";
        prelude: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        recurrent: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            minLoopIters: number;
            maxLoopIters: number;
            allowBacktracking: boolean;
            allowParallelPaths: boolean;
            maxTokens?: number | undefined;
        };
        coda: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        loop: {
            minLoopIters: number;
            maxLoopIters: number;
            maxRevisionDepth: number;
        };
        confidence: {
            thresholds: {
                earlyExit: number;
                revise: number;
                floor: number;
            };
            adaptive: boolean;
            adaptUpDelta: number;
            adaptDownDelta: number;
            smoothingFactor: number;
        };
        attention: {
            defaultMode: "mla" | "gqa" | "auto";
            switchByTask: boolean;
            modeSwitchComplexityThreshold: number;
            moe: {
                enabled: boolean;
                routedExperts: string[];
                sharedExperts: string[];
                topK: number;
                maxParallelExperts: number;
                loadBalanceWindow: number;
            };
        };
        quality: {
            enableTraceLogging: boolean;
            preserveReasoningChain: boolean;
            computeAdaptive: boolean;
            enableMultiHop: boolean;
        };
    }, {
        loop: {
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            maxRevisionDepth?: number | undefined;
        };
        confidence: {
            thresholds: {
                earlyExit?: number | undefined;
                revise?: number | undefined;
                floor?: number | undefined;
            };
            adaptive?: boolean | undefined;
            adaptUpDelta?: number | undefined;
            adaptDownDelta?: number | undefined;
            smoothingFactor?: number | undefined;
        };
        attention: {
            moe: {
                enabled?: boolean | undefined;
                routedExperts?: string[] | undefined;
                sharedExperts?: string[] | undefined;
                topK?: number | undefined;
                maxParallelExperts?: number | undefined;
                loadBalanceWindow?: number | undefined;
            };
            defaultMode?: "mla" | "gqa" | "auto" | undefined;
            switchByTask?: boolean | undefined;
            modeSwitchComplexityThreshold?: number | undefined;
        };
        quality: {
            enableTraceLogging?: boolean | undefined;
            preserveReasoningChain?: boolean | undefined;
            computeAdaptive?: boolean | undefined;
            enableMultiHop?: boolean | undefined;
        };
        enabled?: boolean | undefined;
        profile?: "shallow" | "balanced" | "deep" | undefined;
        prelude?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
        recurrent?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            allowBacktracking?: boolean | undefined;
            allowParallelPaths?: boolean | undefined;
        } | undefined;
        coda?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
    }>, {
        enabled: boolean;
        profile: "shallow" | "balanced" | "deep";
        prelude: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        recurrent: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            minLoopIters: number;
            maxLoopIters: number;
            allowBacktracking: boolean;
            allowParallelPaths: boolean;
            maxTokens?: number | undefined;
        };
        coda: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        loop: {
            minLoopIters: number;
            maxLoopIters: number;
            maxRevisionDepth: number;
        };
        confidence: {
            thresholds: {
                earlyExit: number;
                revise: number;
                floor: number;
            };
            adaptive: boolean;
            adaptUpDelta: number;
            adaptDownDelta: number;
            smoothingFactor: number;
        };
        attention: {
            defaultMode: "mla" | "gqa" | "auto";
            switchByTask: boolean;
            modeSwitchComplexityThreshold: number;
            moe: {
                enabled: boolean;
                routedExperts: string[];
                sharedExperts: string[];
                topK: number;
                maxParallelExperts: number;
                loadBalanceWindow: number;
            };
        };
        quality: {
            enableTraceLogging: boolean;
            preserveReasoningChain: boolean;
            computeAdaptive: boolean;
            enableMultiHop: boolean;
        };
    }, {
        loop: {
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            maxRevisionDepth?: number | undefined;
        };
        confidence: {
            thresholds: {
                earlyExit?: number | undefined;
                revise?: number | undefined;
                floor?: number | undefined;
            };
            adaptive?: boolean | undefined;
            adaptUpDelta?: number | undefined;
            adaptDownDelta?: number | undefined;
            smoothingFactor?: number | undefined;
        };
        attention: {
            moe: {
                enabled?: boolean | undefined;
                routedExperts?: string[] | undefined;
                sharedExperts?: string[] | undefined;
                topK?: number | undefined;
                maxParallelExperts?: number | undefined;
                loadBalanceWindow?: number | undefined;
            };
            defaultMode?: "mla" | "gqa" | "auto" | undefined;
            switchByTask?: boolean | undefined;
            modeSwitchComplexityThreshold?: number | undefined;
        };
        quality: {
            enableTraceLogging?: boolean | undefined;
            preserveReasoningChain?: boolean | undefined;
            computeAdaptive?: boolean | undefined;
            enableMultiHop?: boolean | undefined;
        };
        enabled?: boolean | undefined;
        profile?: "shallow" | "balanced" | "deep" | undefined;
        prelude?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
        recurrent?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            allowBacktracking?: boolean | undefined;
            allowParallelPaths?: boolean | undefined;
        } | undefined;
        coda?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
    }>;
    learning: z.ZodObject<{
        enabled: z.ZodDefault<z.ZodBoolean>;
        approvalMode: z.ZodDefault<z.ZodEnum<["auto", "manual", "optional_human"]>>;
        autoApplyLowRisk: z.ZodDefault<z.ZodBoolean>;
        maxProposalsPerCycle: z.ZodDefault<z.ZodNumber>;
        minObservationsForProposal: z.ZodDefault<z.ZodNumber>;
        observeWindowSize: z.ZodDefault<z.ZodNumber>;
        maxModificationsPerHour: z.ZodDefault<z.ZodNumber>;
        maxToolCreationsPerDay: z.ZodDefault<z.ZodNumber>;
        abTestSampleSize: z.ZodDefault<z.ZodNumber>;
        maxLatencyRegressionRatio: z.ZodDefault<z.ZodNumber>;
        minSuccessRateGain: z.ZodDefault<z.ZodNumber>;
        maxResourceCostPerTestMs: z.ZodDefault<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        enabled: boolean;
        approvalMode: "auto" | "manual" | "optional_human";
        autoApplyLowRisk: boolean;
        maxProposalsPerCycle: number;
        minObservationsForProposal: number;
        observeWindowSize: number;
        maxModificationsPerHour: number;
        maxToolCreationsPerDay: number;
        abTestSampleSize: number;
        maxLatencyRegressionRatio: number;
        minSuccessRateGain: number;
        maxResourceCostPerTestMs: number;
    }, {
        enabled?: boolean | undefined;
        approvalMode?: "auto" | "manual" | "optional_human" | undefined;
        autoApplyLowRisk?: boolean | undefined;
        maxProposalsPerCycle?: number | undefined;
        minObservationsForProposal?: number | undefined;
        observeWindowSize?: number | undefined;
        maxModificationsPerHour?: number | undefined;
        maxToolCreationsPerDay?: number | undefined;
        abTestSampleSize?: number | undefined;
        maxLatencyRegressionRatio?: number | undefined;
        minSuccessRateGain?: number | undefined;
        maxResourceCostPerTestMs?: number | undefined;
    }>;
    interview: z.ZodObject<{
        enabled: z.ZodDefault<z.ZodBoolean>;
        requireForComplexBuilds: z.ZodDefault<z.ZodBoolean>;
        complexityThreshold: z.ZodDefault<z.ZodNumber>;
        maxQuestions: z.ZodDefault<z.ZodNumber>;
        allowBypassForSimpleRequests: z.ZodDefault<z.ZodBoolean>;
        allowOverrideByFlag: z.ZodDefault<z.ZodBoolean>;
        template: z.ZodDefault<z.ZodEnum<["auto", "web_app", "data_pipeline", "api_service", "tool_utility", "general"]>>;
    }, "strip", z.ZodTypeAny, {
        enabled: boolean;
        requireForComplexBuilds: boolean;
        complexityThreshold: number;
        maxQuestions: number;
        allowBypassForSimpleRequests: boolean;
        allowOverrideByFlag: boolean;
        template: "auto" | "web_app" | "data_pipeline" | "api_service" | "tool_utility" | "general";
    }, {
        enabled?: boolean | undefined;
        requireForComplexBuilds?: boolean | undefined;
        complexityThreshold?: number | undefined;
        maxQuestions?: number | undefined;
        allowBypassForSimpleRequests?: boolean | undefined;
        allowOverrideByFlag?: boolean | undefined;
        template?: "auto" | "web_app" | "data_pipeline" | "api_service" | "tool_utility" | "general" | undefined;
    }>;
}, "strip", z.ZodTypeAny, {
    runtime: {
        maxTurns: number;
        maxToolCallsPerTurn: number;
        enableStreamingTools: boolean;
    };
    providers: {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        };
        fallbacks: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight: number;
        }[];
        retry: {
            maxAttempts: number;
            baseDelayMs: number;
            maxDelayMs: number;
            jitterRatio: number;
        };
        circuitBreaker: {
            failureThreshold: number;
            resetTimeoutMs: number;
            halfOpenMaxRequests: number;
        };
        rateLimit: {
            maxRequestsPerMinute: number;
            burst: number;
        };
        observability: {
            debug: boolean;
        };
        credentials: {
            openai?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight: number;
                enabled: boolean;
                models: string[];
                headers: Record<string, string>;
                requestSizeLimitBytes: number;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        gracefulDegradationMessage?: string | undefined;
    };
    rdt: {
        enabled: boolean;
        profile: "shallow" | "balanced" | "deep";
        prelude: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        recurrent: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            minLoopIters: number;
            maxLoopIters: number;
            allowBacktracking: boolean;
            allowParallelPaths: boolean;
            maxTokens?: number | undefined;
        };
        coda: {
            enabled: boolean;
            temperature: number;
            systemInstruction: string;
            maxTokens?: number | undefined;
        };
        loop: {
            minLoopIters: number;
            maxLoopIters: number;
            maxRevisionDepth: number;
        };
        confidence: {
            thresholds: {
                earlyExit: number;
                revise: number;
                floor: number;
            };
            adaptive: boolean;
            adaptUpDelta: number;
            adaptDownDelta: number;
            smoothingFactor: number;
        };
        attention: {
            defaultMode: "mla" | "gqa" | "auto";
            switchByTask: boolean;
            modeSwitchComplexityThreshold: number;
            moe: {
                enabled: boolean;
                routedExperts: string[];
                sharedExperts: string[];
                topK: number;
                maxParallelExperts: number;
                loadBalanceWindow: number;
            };
        };
        quality: {
            enableTraceLogging: boolean;
            preserveReasoningChain: boolean;
            computeAdaptive: boolean;
            enableMultiHop: boolean;
        };
    };
    learning: {
        enabled: boolean;
        approvalMode: "auto" | "manual" | "optional_human";
        autoApplyLowRisk: boolean;
        maxProposalsPerCycle: number;
        minObservationsForProposal: number;
        observeWindowSize: number;
        maxModificationsPerHour: number;
        maxToolCreationsPerDay: number;
        abTestSampleSize: number;
        maxLatencyRegressionRatio: number;
        minSuccessRateGain: number;
        maxResourceCostPerTestMs: number;
    };
    interview: {
        enabled: boolean;
        requireForComplexBuilds: boolean;
        complexityThreshold: number;
        maxQuestions: number;
        allowBypassForSimpleRequests: boolean;
        allowOverrideByFlag: boolean;
        template: "auto" | "web_app" | "data_pipeline" | "api_service" | "tool_utility" | "general";
    };
}, {
    runtime: {
        maxTurns?: number | undefined;
        maxToolCallsPerTurn?: number | undefined;
        enableStreamingTools?: boolean | undefined;
    };
    providers: {
        primary: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        };
        retry: {
            maxAttempts?: number | undefined;
            baseDelayMs?: number | undefined;
            maxDelayMs?: number | undefined;
            jitterRatio?: number | undefined;
        };
        circuitBreaker: {
            failureThreshold?: number | undefined;
            resetTimeoutMs?: number | undefined;
            halfOpenMaxRequests?: number | undefined;
        };
        rateLimit: {
            maxRequestsPerMinute?: number | undefined;
            burst?: number | undefined;
        };
        observability: {
            debug?: boolean | undefined;
        };
        credentials: {
            openai?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            anthropic?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            ollama?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            vllm?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
            custom?: {
                weight?: number | undefined;
                apiKey?: string | undefined;
                baseUrl?: string | undefined;
                organization?: string | undefined;
                protocol?: "openai_chat" | "anthropic_messages" | undefined;
                timeoutMs?: number | undefined;
                enabled?: boolean | undefined;
                models?: string[] | undefined;
                headers?: Record<string, string> | undefined;
                requestSizeLimitBytes?: number | undefined;
                requireApiKey?: boolean | undefined;
            } | undefined;
        };
        fallbacks?: {
            provider: "openai" | "anthropic" | "ollama" | "vllm" | "custom";
            model: string;
            weight?: number | undefined;
        }[] | undefined;
        gracefulDegradationMessage?: string | undefined;
    };
    rdt: {
        loop: {
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            maxRevisionDepth?: number | undefined;
        };
        confidence: {
            thresholds: {
                earlyExit?: number | undefined;
                revise?: number | undefined;
                floor?: number | undefined;
            };
            adaptive?: boolean | undefined;
            adaptUpDelta?: number | undefined;
            adaptDownDelta?: number | undefined;
            smoothingFactor?: number | undefined;
        };
        attention: {
            moe: {
                enabled?: boolean | undefined;
                routedExperts?: string[] | undefined;
                sharedExperts?: string[] | undefined;
                topK?: number | undefined;
                maxParallelExperts?: number | undefined;
                loadBalanceWindow?: number | undefined;
            };
            defaultMode?: "mla" | "gqa" | "auto" | undefined;
            switchByTask?: boolean | undefined;
            modeSwitchComplexityThreshold?: number | undefined;
        };
        quality: {
            enableTraceLogging?: boolean | undefined;
            preserveReasoningChain?: boolean | undefined;
            computeAdaptive?: boolean | undefined;
            enableMultiHop?: boolean | undefined;
        };
        enabled?: boolean | undefined;
        profile?: "shallow" | "balanced" | "deep" | undefined;
        prelude?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
        recurrent?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
            minLoopIters?: number | undefined;
            maxLoopIters?: number | undefined;
            allowBacktracking?: boolean | undefined;
            allowParallelPaths?: boolean | undefined;
        } | undefined;
        coda?: {
            systemInstruction: string;
            enabled?: boolean | undefined;
            temperature?: number | undefined;
            maxTokens?: number | undefined;
        } | undefined;
    };
    learning: {
        enabled?: boolean | undefined;
        approvalMode?: "auto" | "manual" | "optional_human" | undefined;
        autoApplyLowRisk?: boolean | undefined;
        maxProposalsPerCycle?: number | undefined;
        minObservationsForProposal?: number | undefined;
        observeWindowSize?: number | undefined;
        maxModificationsPerHour?: number | undefined;
        maxToolCreationsPerDay?: number | undefined;
        abTestSampleSize?: number | undefined;
        maxLatencyRegressionRatio?: number | undefined;
        minSuccessRateGain?: number | undefined;
        maxResourceCostPerTestMs?: number | undefined;
    };
    interview: {
        enabled?: boolean | undefined;
        requireForComplexBuilds?: boolean | undefined;
        complexityThreshold?: number | undefined;
        maxQuestions?: number | undefined;
        allowBypassForSimpleRequests?: boolean | undefined;
        allowOverrideByFlag?: boolean | undefined;
        template?: "auto" | "web_app" | "data_pipeline" | "api_service" | "tool_utility" | "general" | undefined;
    };
}>;
//# sourceMappingURL=schema.d.ts.map