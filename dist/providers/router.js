import { detectAnthropicProtocol } from './protocols/anthropic.adapter.js';
import { detectOpenAICompatibleProtocol } from './protocols/openai.adapter.js';
import { enforceTokenBudget, estimateRequestTokens } from './tokens.js';
import { ProviderMetrics, StructuredLogger, isTransientError, sanitizeError } from './observability.js';
function routeKey(route) {
    return `${route.provider}:${route.model}`;
}
function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
}
class InMemoryProviderRegistry {
    providers;
    constructor(providers) {
        this.providers = providers;
    }
    get(provider) {
        return this.providers.get(provider);
    }
    list() {
        return [...this.providers.values()];
    }
}
export class ProviderRouterImpl {
    chain;
    stateByRoute = new Map();
    requestsByProvider = new Map();
    registry;
    logger;
    metrics = new ProviderMetrics();
    constructor(providers, chain) {
        this.chain = chain;
        this.registry = new InMemoryProviderRegistry(new Map(providers.map((provider) => [provider.key, provider])));
        this.logger = new StructuredLogger('provider.router', chain.observability.debug);
    }
    /** Plans the primary/fallback provider chain for a given turn input. */
    async plan(input) {
        const ranked = input.routes
            .map((route, index) => ({ route, score: this.scoreRoute(route, input, index), index }))
            .filter((candidate) => Number.isFinite(candidate.score) && candidate.score > Number.NEGATIVE_INFINITY)
            .sort((a, b) => b.score - a.score || a.index - b.index)
            .map((candidate) => candidate.route);
        if (ranked.length === 0) {
            throw this.error('recoverable_provider_error', 'No eligible provider routes after capability and credential checks.');
        }
        this.logger.log('info', 'Provider plan selected.', {
            primary: ranked[0],
            fallbacks: ranked.slice(1)
        });
        return {
            primary: ranked[0],
            fallbacks: ranked.slice(1)
        };
    }
    /** Selects the next fallback route when the attempted route fails. */
    async onProviderFailure(ctx) {
        const allRoutes = [ctx.plan.primary, ...ctx.plan.fallbacks];
        const index = allRoutes.findIndex((route) => route.provider === ctx.attemptedRoute.provider && route.model === ctx.attemptedRoute.model);
        for (let i = index + 1; i < allRoutes.length; i += 1) {
            const candidate = allRoutes[i];
            if (!this.isCircuitOpen(candidate)) {
                return candidate;
            }
        }
        return null;
    }
    /** Executes a streaming request with retry, circuit breaker and fallback behavior. */
    async *streamWithFallback(userInput, messages, plan, emitMeta) {
        const routes = [plan.primary, ...plan.fallbacks];
        let finalText = '';
        for (let routeIndex = 0; routeIndex < routes.length; routeIndex += 1) {
            const route = routes[routeIndex];
            const provider = this.registry.get(route.provider);
            const routeId = routeKey(route);
            if (!provider) {
                this.logger.log('warn', 'Skipping unknown provider route.', { route });
                continue;
            }
            if (this.isCircuitOpen(route)) {
                this.logger.log('warn', 'Skipping route because circuit is open.', { route });
                continue;
            }
            await emitMeta({ type: 'provider_selected', route });
            for (let attempt = 1; attempt <= this.chain.retry.maxAttempts; attempt += 1) {
                const startedAt = Date.now();
                this.metrics.recordAttempt(routeId);
                try {
                    this.enforceRateLimit(route);
                    const estimate = estimateRequestTokens(provider, route.model, messages);
                    const budgetCheck = enforceTokenBudget(estimate);
                    if (!budgetCheck.allowed) {
                        throw this.error('budget_exhausted', budgetCheck.reason ?? 'Token budget exceeded');
                    }
                    const request = {
                        sessionId: userInput.sessionId,
                        model: route.model,
                        messages,
                        stream: true,
                        maxOutputTokens: estimate.maxOutputTokens,
                        metadata: {
                            mode: userInput.mode
                        }
                    };
                    let sawCompletion = false;
                    for await (const event of provider.stream(request)) {
                        if (event.type === 'delta') {
                            finalText += event.text;
                            yield event.text;
                            continue;
                        }
                        if (event.type === 'done') {
                            sawCompletion = true;
                            if (event.response.text) {
                                finalText += event.response.text;
                            }
                            continue;
                        }
                        if (event.type === 'error') {
                            throw event.error;
                        }
                    }
                    if (!sawCompletion && finalText.length === 0) {
                        throw this.error('provider_unavailable', 'Provider stream ended without completion output.');
                    }
                    this.onSuccess(route);
                    this.metrics.recordSuccess(routeId, Date.now() - startedAt);
                    this.logDegradedPerformance(route);
                    return finalText;
                }
                catch (error) {
                    this.onFailure(route);
                    const normalized = sanitizeError(error);
                    this.metrics.recordFailure(routeId, Date.now() - startedAt);
                    this.logger.log('warn', 'Provider request failed.', {
                        route,
                        attempt,
                        code: normalized.code,
                        message: normalized.message
                    });
                    if (attempt < this.chain.retry.maxAttempts && isTransientError(normalized)) {
                        const delayMs = this.retryDelay(attempt);
                        this.logger.log('info', 'Retry scheduled.', { route, attempt, delayMs });
                        await emitMeta({
                            type: 'retry_scheduled',
                            delayMs,
                            reason: `${route.provider}:${route.model} -> ${normalized.message}`
                        });
                        await sleep(delayMs);
                        continue;
                    }
                    const nextRoute = await this.onProviderFailure({
                        attemptedRoute: route,
                        error: normalized,
                        plan,
                        attempt
                    });
                    if (nextRoute) {
                        this.logger.log('warn', 'Fallback activated.', { from: route, to: nextRoute });
                        await emitMeta({ type: 'fallback_activated', route: nextRoute });
                    }
                    break;
                }
            }
        }
        const degraded = this.chain.gracefulDegradationMessage ??
            'All providers are currently unavailable. Please retry shortly.';
        this.logger.log('error', 'All provider routes exhausted; returning graceful degradation message.');
        return degraded;
    }
    /** Detects protocol type for a candidate model string. */
    detectProtocol(model) {
        if (detectAnthropicProtocol(model)) {
            return 'anthropic_messages';
        }
        if (detectOpenAICompatibleProtocol(model)) {
            return 'openai_chat';
        }
        return 'openai_chat';
    }
    scoreRoute(route, input, index) {
        const provider = this.registry.get(route.provider);
        if (!provider || provider.config.enabled === false) {
            return Number.NEGATIVE_INFINITY;
        }
        if (!provider.supportsModel(route.model)) {
            return Number.NEGATIVE_INFINITY;
        }
        const missingCredentials = (route.provider === 'openai' && !(provider.config.apiKey ?? process.env.OPENAI_API_KEY)) ||
            (route.provider === 'anthropic' && !(provider.config.apiKey ?? process.env.ANTHROPIC_API_KEY));
        if (missingCredentials) {
            this.logger.log('warn', 'Route rejected due to missing credentials.', { route });
            return Number.NEGATIVE_INFINITY;
        }
        const protocol = this.detectProtocol(route.model);
        if (!provider.capabilities.protocols.includes(protocol)) {
            return Number.NEGATIVE_INFINITY;
        }
        const estimate = provider.estimateTokens([{ role: 'user', content: input.userInput.userMessage }], route.model);
        const budgetCheck = enforceTokenBudget(estimate, input.tokenBudget);
        if (!budgetCheck.allowed) {
            this.logger.log('warn', 'Route rejected due to token budget.', { route, reason: budgetCheck.reason });
            return Number.NEGATIVE_INFINITY;
        }
        const routeHealth = this.routeHealthScore(route);
        const weight = provider.config.weight ?? 1;
        const priorityBias = Math.max(0, input.routes.length - index) * 100;
        return priorityBias + routeHealth + weight;
    }
    routeHealthScore(route) {
        const state = this.stateByRoute.get(routeKey(route));
        if (!state) {
            return 1;
        }
        if (state.openedAt && Date.now() - state.openedAt < this.chain.circuitBreaker.resetTimeoutMs) {
            return Number.NEGATIVE_INFINITY;
        }
        return Math.max(0.1, 1 - state.failures * 0.2);
    }
    isCircuitOpen(route) {
        const state = this.stateByRoute.get(routeKey(route));
        if (!state?.openedAt) {
            return false;
        }
        const elapsed = Date.now() - state.openedAt;
        if (elapsed > this.chain.circuitBreaker.resetTimeoutMs) {
            const currentProbes = state.halfOpenProbeCount ?? 0;
            if (currentProbes < this.chain.circuitBreaker.halfOpenMaxRequests) {
                state.halfOpenProbeCount = currentProbes + 1;
                this.logger.log('info', 'Circuit breaker transitioned to half-open probe.', { route, probe: state.halfOpenProbeCount });
                return false;
            }
        }
        return elapsed <= this.chain.circuitBreaker.resetTimeoutMs;
    }
    onFailure(route) {
        const key = routeKey(route);
        const state = this.stateByRoute.get(key) ?? { failures: 0, halfOpenProbeCount: 0 };
        state.failures += 1;
        if (state.failures >= this.chain.circuitBreaker.failureThreshold) {
            const wasOpen = !!state.openedAt;
            state.openedAt = Date.now();
            state.halfOpenProbeCount = 0;
            if (!wasOpen) {
                this.logger.log('warn', 'Circuit breaker opened.', { route, failures: state.failures });
            }
        }
        this.stateByRoute.set(key, state);
    }
    onSuccess(route) {
        const key = routeKey(route);
        const previous = this.stateByRoute.get(key);
        if (previous?.openedAt) {
            this.logger.log('info', 'Circuit breaker closed after successful probe.', { route });
        }
        this.stateByRoute.set(key, { failures: 0, halfOpenProbeCount: 0 });
    }
    retryDelay(attempt) {
        const exponential = this.chain.retry.baseDelayMs * 2 ** (attempt - 1);
        const bounded = Math.min(exponential, this.chain.retry.maxDelayMs);
        const jitterRatio = this.chain.retry.jitterRatio ?? 0.2;
        const jitter = bounded * jitterRatio * Math.random();
        return Math.floor(bounded + jitter);
    }
    error(code, message) {
        return { code, message };
    }
    enforceRateLimit(route) {
        const key = route.provider;
        const now = Date.now();
        const current = this.requestsByProvider.get(key) ?? { count: 0, windowStartMs: now };
        const elapsed = now - current.windowStartMs;
        const windowMs = 60_000;
        if (elapsed >= windowMs) {
            current.count = 0;
            current.windowStartMs = now;
        }
        current.count += 1;
        this.requestsByProvider.set(key, current);
        if (current.count > this.chain.rateLimit.maxRequestsPerMinute || current.count > this.chain.rateLimit.burst) {
            throw this.error('rate_limited', `Rate limit exceeded for provider ${route.provider}.`);
        }
    }
    logDegradedPerformance(route) {
        const snapshot = this.metrics.snapshot(routeKey(route));
        if (snapshot.attempts >= 5 && snapshot.successRate < 0.5) {
            this.logger.log('warn', 'Provider performance is degraded.', {
                route,
                attempts: snapshot.attempts,
                successRate: snapshot.successRate,
                avgLatencyMs: snapshot.avgLatencyMs
            });
        }
    }
}
//# sourceMappingURL=router.js.map