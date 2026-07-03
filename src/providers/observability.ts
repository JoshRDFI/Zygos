import type { ZygosError } from '../types/core.types.js';

const REDACTION = '[REDACTED]';
const SENSITIVE_KEYS = ['authorization', 'api_key', 'apikey', 'token', 'secret', 'password', 'x-api-key'];

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

export function redactSensitive(value: unknown): unknown {
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
    const objectValue = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(objectValue).map(([key, nested]) => {
        if (SENSITIVE_KEYS.some((sensitiveKey) => key.toLowerCase().includes(sensitiveKey))) {
          return [key, REDACTION];
        }
        return [key, redactSensitive(nested)];
      })
    );
  }

  return value;
}

export class StructuredLogger {
  constructor(private readonly component: string, private readonly debugEnabled = false) {}

  log(level: LogLevel, message: string, details?: Record<string, unknown>): void {
    if (level === 'debug' && !this.debugEnabled) {
      return;
    }
    const payload: LogEntry = {
      level,
      message,
      component: this.component,
      ts: new Date().toISOString(),
      ...(details ? { details: redactSensitive(details) as Record<string, unknown> } : {})
    };
    // eslint-disable-next-line no-console
    console[level === 'debug' ? 'log' : level](JSON.stringify(payload));
  }
}

export class ProviderMetrics {
  private readonly stats = new Map<string, { attempts: number; successes: number; failures: number; totalLatencyMs: number }>();

  recordAttempt(routeId: string): void {
    const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
    state.attempts += 1;
    this.stats.set(routeId, state);
  }

  recordSuccess(routeId: string, latencyMs: number): void {
    const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
    state.successes += 1;
    state.totalLatencyMs += Math.max(0, latencyMs);
    this.stats.set(routeId, state);
  }

  recordFailure(routeId: string, latencyMs: number): void {
    const state = this.stats.get(routeId) ?? { attempts: 0, successes: 0, failures: 0, totalLatencyMs: 0 };
    state.failures += 1;
    state.totalLatencyMs += Math.max(0, latencyMs);
    this.stats.set(routeId, state);
  }

  snapshot(routeId: string): ProviderMetricSnapshot {
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
  private prepares = 0;
  private compactions = 0;
  private searches = 0;
  private prepareLatencyMs = 0;
  private searchLatencyMs = 0;

  recordPrepare(durationMs: number): void {
    this.prepares += 1;
    this.prepareLatencyMs += Math.max(0, durationMs);
  }

  recordCompaction(): void {
    this.compactions += 1;
  }

  recordSearch(durationMs: number): void {
    this.searches += 1;
    this.searchLatencyMs += Math.max(0, durationMs);
  }

  snapshot(): ContextMetricSnapshot {
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
  private runs = 0;
  private loops = 0;
  private haltedEarly = 0;
  private totalFinalConfidence = 0;
  private totalQuality = 0;

  recordRun(input: { loopsUsed: number; haltedEarly: boolean; finalConfidence: number; avgQuality: number }): void {
    this.runs += 1;
    this.loops += Math.max(0, input.loopsUsed);
    if (input.haltedEarly) {
      this.haltedEarly += 1;
    }
    this.totalFinalConfidence += Math.max(0, input.finalConfidence);
    this.totalQuality += Math.max(0, input.avgQuality);
  }

  snapshot(): RdtMetricSnapshot {
    return {
      runs: this.runs,
      loops: this.loops,
      haltedEarly: this.haltedEarly,
      averageFinalConfidence: this.runs > 0 ? this.totalFinalConfidence / this.runs : 0,
      averageQuality: this.runs > 0 ? this.totalQuality / this.runs : 0
    };
  }
}

export function sanitizeError(error: unknown): ZygosError {
  if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
    const known = error as ZygosError;
    return {
      ...known,
      details: known.details ? (redactSensitive(known.details) as Record<string, unknown>) : undefined
    };
  }

  const message = error instanceof Error ? error.message : String(error);
  return {
    code: 'recoverable_provider_error',
    message: message.slice(0, 500)
  };
}

export function isTransientError(error: ZygosError): boolean {
  const message = error.message.toLowerCase();
  if (error.code === 'network_timeout' || error.code === 'rate_limited' || error.code === 'recoverable_provider_error') {
    return true;
  }

  return (
    message.includes('timeout') ||
    message.includes('connection') ||
    message.includes('temporar') ||
    message.includes('429') ||
    message.includes('503')
  );
}
