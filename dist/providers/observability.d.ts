import type { HarnessError } from '../types/core.types.js';
export type LogLevel = 'debug' | 'info' | 'warn' | 'error';
export interface LogEntry {
    level: LogLevel;
    message: string;
    component: string;
    ts: string;
    details?: Record<string, unknown>;
}
export interface ProviderMetricSnapshot {
    attempts: number;
    successes: number;
    failures: number;
    avgLatencyMs: number;
    successRate: number;
}
export interface ContextMetricSnapshot {
    prepares: number;
    compactions: number;
    searches: number;
    averagePrepareMs: number;
    averageSearchMs: number;
}
export interface RdtMetricSnapshot {
    runs: number;
    loops: number;
    haltedEarly: number;
    averageFinalConfidence: number;
    averageQuality: number;
}
export declare function redactSensitive(value: unknown): unknown;
export declare class StructuredLogger {
    private readonly component;
    private readonly debugEnabled;
    constructor(component: string, debugEnabled?: boolean);
    log(level: LogLevel, message: string, details?: Record<string, unknown>): void;
}
export declare class ProviderMetrics {
    private readonly stats;
    recordAttempt(routeId: string): void;
    recordSuccess(routeId: string, latencyMs: number): void;
    recordFailure(routeId: string, latencyMs: number): void;
    snapshot(routeId: string): ProviderMetricSnapshot;
}
export declare class ContextMetrics {
    private prepares;
    private compactions;
    private searches;
    private prepareLatencyMs;
    private searchLatencyMs;
    recordPrepare(durationMs: number): void;
    recordCompaction(): void;
    recordSearch(durationMs: number): void;
    snapshot(): ContextMetricSnapshot;
}
export declare class RdtMetrics {
    private runs;
    private loops;
    private haltedEarly;
    private totalFinalConfidence;
    private totalQuality;
    recordRun(input: {
        loopsUsed: number;
        haltedEarly: boolean;
        finalConfidence: number;
        avgQuality: number;
    }): void;
    snapshot(): RdtMetricSnapshot;
}
export declare function sanitizeError(error: unknown): HarnessError;
export declare function isTransientError(error: HarnessError): boolean;
//# sourceMappingURL=observability.d.ts.map