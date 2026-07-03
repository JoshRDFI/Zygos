import type { EngineEvent, ProviderRoute, UserTurnInput } from '../types/core.types.js';
import type { FallbackChainConfig, ModelRequest, Provider, ProviderFailureContext, ProviderPlan, ProviderPlanningInput } from '../types/provider.types.js';
export declare class ProviderRouterImpl {
    private readonly chain;
    private readonly stateByRoute;
    private readonly requestsByProvider;
    private readonly registry;
    private readonly logger;
    private readonly metrics;
    constructor(providers: Provider[], chain: FallbackChainConfig);
    /** Plans the primary/fallback provider chain for a given turn input. */
    plan(input: ProviderPlanningInput): Promise<ProviderPlan>;
    /** Selects the next fallback route when the attempted route fails. */
    onProviderFailure(ctx: ProviderFailureContext): Promise<ProviderRoute | null>;
    /** Executes a streaming request with retry, circuit breaker and fallback behavior. */
    streamWithFallback(userInput: UserTurnInput, messages: ModelRequest['messages'], plan: ProviderPlan, emitMeta: (event: Extract<EngineEvent, {
        type: 'retry_scheduled' | 'fallback_activated' | 'provider_selected';
    }>) => Promise<void>): AsyncGenerator<string, string, void>;
    /** Detects protocol type for a candidate model string. */
    detectProtocol(model: string): 'anthropic_messages' | 'openai_chat';
    private scoreRoute;
    private routeHealthScore;
    private isCircuitOpen;
    private onFailure;
    private onSuccess;
    private retryDelay;
    private error;
    private enforceRateLimit;
    private logDegradedPerformance;
}
//# sourceMappingURL=router.d.ts.map