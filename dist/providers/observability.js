const REDACTION = '[REDACTED]';
const SENSITIVE_KEYS = ['authorization', 'api_key', 'apikey', 'token', 'secret', 'password', 'x-api-key'];
export function redactSensitive(value) {
    if (typeof value === 'string') {
        if (value.startsWith('Bearer ') || value.length > 80) {
            return REDACTION;
        }
        return value;
    }
    if (Array.isArray(value)) {
        return value.map((entry) => redactSensitive(entry));
    }
    if (value && typeof value === 'object') {
        const objectValue = value;
        return Object.fromEntries(Object.entries(objectValue).map(([key, nested]) => {
            if (SENSITIVE_KEYS.some((sensitiveKey) => key.toLowerCase().includes(sensitiveKey))) {
                return [key, REDACTION];
            }
            return [key, redactSensitive(nested)];
        }));
    }
    return value;
}
export class StructuredLogger {
    component;
    debugEnabled;
    constructor(component, debugEnabled = false) {
        this.component = component;
        this.debugEnabled = debugEnabled;
    }
    log(level, message, details) {
        if (level === 'debug' && !this.debugEnabled) {
            return;
        }
        const payload = {
            level,
            message,
            component: this.component,
            ts: new Date().toISOString(),
            ...(details ? { details: redactSensitive(details) } : {})
        };
        // eslint-disable-next-line no-console
        console[level === 'debug' ? 'log' : level](JSON.stringify(payload));
    }
}
export class ProviderMetrics {
    stats = new Map();
    recordAttempt(routeId) {
        const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
        state.attempts += 1;
        this.stats.set(routeId, state);
    }
    recordSuccess(routeId, latencyMs) {
        const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
        state.successes += 1;
        state.totalLatencyMs += Math.max(0, latencyMs);
        this.stats.set(routeId, state);
    }
    recordFailure(routeId, latencyMs) {
        const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
        state.failures += 1;
        state.totalLatencyMs += Math.max(0, latencyMs);
        this.stats.set(routeId, state);
    }
    snapshot(routeId) {
        const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
        const completed = state.successes + state.failures;
        return {
            attempts: state.attempts,
            successes: state.successes,
            failures: state.failures,
            avgLatencyMs: completed > 0 ? state.totalLatencyMs / completed : 0,
            successRate: completed > 0 ? state.successes / completed : 0
        };
    }
}
export class ContextMetrics {
    prepares = 0;
    compactions = 0;
    searches = 0;
    prepareLatencyMs = 0;
    searchLatencyMs = 0;
    recordPrepare(durationMs) {
        this.prepares += 1;
        this.prepareLatencyMs += Math.max(0, durationMs);
    }
    recordCompaction() {
        this.compactions += 1;
    }
    recordSearch(durationMs) {
        this.searches += 1;
        this.searchLatencyMs += Math.max(0, durationMs);
    }
    snapshot() {
        return {
            prepares: this.prepares,
            compactions: this.compactions,
            searches: this.searches,
            averagePrepareMs: this.prepares > 0 ? this.prepareLatencyMs / this.prepares : 0,
            averageSearchMs: this.searches > 0 ? this.searchLatencyMs / this.searches : 0
        };
    }
}
export class RdtMetrics {
    runs = 0;
    loops = 0;
    haltedEarly = 0;
    totalFinalConfidence = 0;
    totalQuality = 0;
    recordRun(input) {
        this.runs += 1;
        this.loops += Math.max(0, input.loopsUsed);
        if (input.haltedEarly) {
            this.haltedEarly += 1;
        }
        this.totalFinalConfidence += Math.max(0, input.finalConfidence);
        this.totalQuality += Math.max(0, input.avgQuality);
    }
    snapshot() {
        return {
            runs: this.runs,
            loops: this.loops,
            haltedEarly: this.haltedEarly,
            averageFinalConfidence: this.runs > 0 ? this.totalFinalConfidence / this.runs : 0,
            averageQuality: this.runs > 0 ? this.totalQuality / this.runs : 0
        };
    }
}
export function sanitizeError(error) {
    if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
        const known = error;
        return {
            ...known,
            details: known.details ? redactSensitive(known.details) : undefined
        };
    }
    const message = error instanceof Error ? error.message : String(error);
    return {
        code: 'recoverable_provider_error',
        message: message.slice(0, 500)
    };
}
export function isTransientError(error) {
    const message = error.message.toLowerCase();
    if (error.code === 'network_timeout' || error.code === 'rate_limited' || error.code === 'recoverable_provider_error') {
        return true;
    }
    return (message.includes('timeout') ||
        message.includes('connection') ||
        message.includes('temporar') ||
        message.includes('429') ||
        message.includes('503'));
}
//# sourceMappingURL=observability.js.map