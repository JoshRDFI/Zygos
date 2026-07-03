import { z } from 'zod';
import type { HarnessError } from '../types/core.types.js';
import type { ModelRequest, ModelResponse, Provider, ProviderCapabilities, ProviderConfig, ProviderStreamEvent, SupportedProviderKey, TokenEstimate, UsageStats } from '../types/provider.types.js';
import { StructuredLogger } from './observability.js';
export declare abstract class BaseProvider implements Provider {
    readonly config: ProviderConfig;
    abstract readonly key: SupportedProviderKey;
    abstract readonly capabilities: ProviderCapabilities;
    protected readonly logger: StructuredLogger;
    constructor(config: ProviderConfig);
    supportsModel(model: string): boolean;
    estimateTokens(messages: ModelRequest['messages'], model: string): TokenEstimate;
    protected get timeoutMs(): number;
    protected get requestSizeLimitBytes(): number;
    protected validateAndSanitizeRequest(request: ModelRequest): ModelRequest;
    protected sanitizeUserInput(text: string): string;
    protected buildHeaders(additional?: Record<string, string>): Record<string, string>;
    protected postJson<T>(url: string, body: unknown, headers?: Record<string, string>, responseSchema?: z.ZodType<T>): Promise<T>;
    protected fetchWithTimeout(url: string, init: RequestInit): Promise<Response>;
    protected streamSSE(response: Response, parser: (data: string) => ProviderStreamEvent[]): AsyncGenerator<ProviderStreamEvent, void, void>;
    protected responseFromText(text: string, usage?: UsageStats, nativeResponse?: unknown): ModelResponse;
    protected safeJson(response: Response): Promise<unknown>;
    protected classifyHttpError(status: number, body?: string): HarnessError;
    protected error(code: HarnessError['code'], message: string, details?: Record<string, unknown>): HarnessError;
    protected assertEndpointSecurity(url: string): void;
    abstract complete(request: ModelRequest): Promise<ModelResponse>;
    abstract stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void>;
}
//# sourceMappingURL=base.provider.d.ts.map