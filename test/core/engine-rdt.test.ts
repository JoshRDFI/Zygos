import test from 'node:test';
import assert from 'node:assert/strict';
import { QueryEngineImpl } from '../../src/core/engine.js';
import { InMemoryStateStore } from '../../src/core/state.js';
import type { EngineEvent, QueryEngineDeps, QuerySessionState, UserTurnInput } from '../../src/types/core.types.js';

const baseConfig = {
  runtime: {
    maxTurns: 3,
    maxToolCallsPerTurn: 1,
    enableStreamingTools: false
  },
  providers: {
    primary: { provider: 'custom', model: 'demo', weight: 1 },
    fallbacks: [],
    retry: { maxAttempts: 1, baseDelayMs: 10, maxDelayMs: 20, jitterRatio: 0 },
    circuitBreaker: { failureThreshold: 2, resetTimeoutMs: 1000, halfOpenMaxRequests: 1 },
    rateLimit: { maxRequestsPerMinute: 100, burst: 10 },
    observability: { debug: false },
    gracefulDegradationMessage: 'degraded',
    credentials: {
      custom: { enabled: true }
    }
  },
  rdt: {
    enabled: true,
    profile: 'balanced',
    prelude: { enabled: true, temperature: 0.1, maxTokens: 128, systemInstruction: 'x' },
    recurrent: {
      enabled: true,
      temperature: 0.2,
      maxTokens: 128,
      minLoopIters: 1,
      maxLoopIters: 2,
      allowBacktracking: true,
      allowParallelPaths: true,
      systemInstruction: 'x'
    },
    coda: { enabled: true, temperature: 0.1, maxTokens: 128, systemInstruction: 'x' },
    loop: { maxLoopIters: 2, minLoopIters: 1, maxRevisionDepth: 1 },
    confidence: {
      thresholds: { earlyExit: 0.8, revise: 0.5, floor: 0.2 },
      adaptive: true,
      adaptUpDelta: 0.03,
      adaptDownDelta: 0.03,
      smoothingFactor: 0.5
    },
    attention: {
      defaultMode: 'auto',
      switchByTask: true,
      modeSwitchComplexityThreshold: 0.5,
      moe: {
        enabled: true,
        routedExperts: ['coding'],
        sharedExperts: ['synthesis'],
        topK: 1,
        maxParallelExperts: 2,
        loadBalanceWindow: 5
      }
    },
    quality: {
      enableTraceLogging: true,
      preserveReasoningChain: true,
      computeAdaptive: true,
      enableMultiHop: true
    }
  }
} as QueryEngineDeps['config'];

test('QueryEngine emits RDT progress and applies RDT final text', async () => {
  const stateStore = new InMemoryStateStore();

  const deps: QueryEngineDeps = {
    config: baseConfig,
    stateStore,
    toolExecutor: {
      executeBatch: async () => []
    },
    pickProviderPlan: async () => ({
      primary: { provider: 'custom', model: 'demo', reason: 'test' },
      fallbacks: []
    }),
    executeModel: async function* (_input: UserTurnInput, _session: QuerySessionState, _emitMeta) {
      yield 'model output';
      return 'model output';
    },
    runRdt: async (_input, _session, emitProgress) => {
      await emitProgress({ type: 'rdt_stage_started', stage: 'prelude' });
      await emitProgress({
        type: 'rdt_iteration_completed',
        iteration: 1,
        confidence: 0.91,
        threshold: 0.8,
        attentionMode: 'mla',
        routedExperts: ['coding'],
        quality: {
          coherence: 0.9,
          completeness: 0.9,
          consistency: 0.9,
          aggregate: 0.9,
          explanation: 'good'
        }
      });

      return {
        finalText: 'rdt output',
        loopsUsed: 1,
        haltedEarly: true,
        finalConfidence: 0.91,
        quality: {
          avgCoherence: 0.9,
          avgCompleteness: 0.9,
          avgConsistency: 0.9,
          avgAggregate: 0.9
        }
      };
    }
  };

  const engine = new QueryEngineImpl(deps);
  const events: EngineEvent[] = [];
  const stream = engine.runTurn({ sessionId: 's1', userMessage: 'hello', mode: 'standard' });
  for await (const event of stream) {
    events.push(event);
  }

  const rdtProgressCount = events.filter((event) => event.type === 'rdt_progress').length;
  assert.ok(rdtProgressCount >= 2);
  const completed = events.find((event) => event.type === 'turn_completed');
  assert.ok(completed && completed.type === 'turn_completed');
  assert.equal(completed.result.finalText, 'rdt output');
  assert.ok(completed.result.rdt?.enabled);
});
