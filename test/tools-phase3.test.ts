import assert from 'node:assert/strict';
import test from 'node:test';
import { setTimeout as sleep } from 'node:timers/promises';
import { z } from 'zod';
import { QueryEngineImpl } from '../src/core/engine.js';
import { InMemoryStateStore } from '../src/core/state.js';
import { ParallelExecutionOrchestrator } from '../src/tools/parallel-executor.js';
import { PermissionManager } from '../src/tools/permissions.js';
import { BasicToolRegistry } from '../src/tools/registry.js';
import { StreamingToolExecutor } from '../src/tools/streaming-executor.js';
import { enforceResultSize, normalizeErrorResult, validateResultFormat } from '../src/tools/validation.js';
import type { EngineEvent, QueryEngineDeps } from '../src/types/core.types.js';

function createCtx() {
  return {
    sessionId: 's-test',
    turnId: 't-test',
    signal: new AbortController().signal
  };
}

test('permission manager requires approval for user destructive tools', async () => {
  const manager = new PermissionManager();
  const result = manager.check(
    {
      name: 'danger.tool',
      description: 'dangerous',
      version: '1.0.0',
      timeoutMs: 100,
      concurrency: 'serial_only',
      destructive: true,
      permission: 'allow',
      aliases: []
    },
    {
      ...createCtx(),
      role: 'user'
    }
  );

  assert.equal(result.allowed, false);
  assert.equal(result.requiresApproval, true);
});

test('validation enforces formats and size and normalizes errors', async () => {
  assert.throws(() => validateResultFormat(new Uint8Array([1]), 'json'));
  assert.throws(() => enforceResultSize('x'.repeat(100), 10));

  const normalized = normalizeErrorResult('c1', new Error('boom'), 10, 'tool_execution_error');
  assert.equal(normalized.ok, false);
  assert.equal(normalized.normalizedError?.code, 'tool_execution_error');
});

test('streaming executor emits progress for streaming tools', async () => {
  const registry = new BasicToolRegistry();
  registry.register({
    meta: {
      name: 'stream_echo',
      description: 'stream chunks',
      timeoutMs: 1_000,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 }
    },
    inputSchema: z.object({ text: z.string() }),
    outputSchema: z.string(),
    async execute(input: { text: string }) {
      return input.text;
    },
    async *executeStream(input: { text: string }) {
      const parts = input.text.split('');
      for (const part of parts) {
        yield part;
      }
      return input.text;
    }
  });

  const executor = new StreamingToolExecutor(registry, { progressChunkSize: 1 });
  const events: string[] = [];
  const stream = executor.executeBatchStream(
    [{ id: 'c1', name: 'stream_echo', input: { text: 'abc' } }],
    { ...createCtx(), role: 'admin' }
  );

  while (true) {
    const next = await stream.next();
    if (next.done) {
      assert.equal(next.value[0]?.ok, true);
      break;
    }
    events.push(next.value.type);
  }

  assert.ok(events.includes('tool_started'));
  assert.ok(events.includes('tool_progress'));
  assert.ok(events.includes('tool_completed'));
});

test('streaming executor returns timeout error for long running tool', async () => {
  const registry = new BasicToolRegistry();
  registry.register({
    meta: {
      name: 'slow_tool',
      description: 'slow',
      timeoutMs: 5,
      concurrency: 'serial_only',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 }
    },
    inputSchema: z.object({}),
    outputSchema: z.object({ ok: z.boolean() }),
    async execute() {
      await sleep(30);
      return { ok: true };
    }
  });

  const executor = new StreamingToolExecutor(registry);
  const result = await executor.execute({ id: 'c2', name: 'slow_tool', input: {} }, { ...createCtx(), role: 'admin' });

  assert.equal(result.ok, false);
  assert.equal(result.normalizedError?.code, 'tool_timeout');
});

test('parallel orchestrator handles dependencies and partial failures', async () => {
  const orchestrator = new ParallelExecutionOrchestrator({ concurrency: 2 });
  const started: string[] = [];

  const { results, failures } = await orchestrator.execute(
    [
      { call: { id: 'a', name: 'a', input: {} }, dependencies: [], parallelSafe: true, resourceKey: 'r1' },
      { call: { id: 'b', name: 'b', input: {} }, dependencies: ['a'], parallelSafe: true, resourceKey: 'r2' },
      { call: { id: 'c', name: 'c', input: {} }, dependencies: [], parallelSafe: true, resourceKey: 'r1' }
    ],
    createCtx(),
    async (call) => {
      started.push(call.id);
      if (call.id === 'c') {
        return {
          toolCallId: call.id,
          ok: false,
          error: 'failed',
          durationMs: 1,
          synthetic: true,
          partial: false,
          warnings: []
        };
      }

      await sleep(5);
      return {
        toolCallId: call.id,
        ok: true,
        output: { id: call.id },
        durationMs: 1,
        synthetic: false,
        partial: false,
        warnings: []
      };
    }
  );

  assert.equal(results.length, 3);
  assert.equal(failures.length, 1);
  assert.ok(started.indexOf('a') < started.indexOf('b'));
});

test('query engine emits tool streaming events from executor', async () => {
  const stateStore = new InMemoryStateStore();
  const registry = new BasicToolRegistry();

  registry.register({
    meta: {
      name: 'stream_echo',
      description: 'stream chunks',
      timeoutMs: 1_000,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 }
    },
    inputSchema: z.object({ text: z.string() }),
    outputSchema: z.string(),
    async execute(input: { text: string }) {
      return input.text;
    },
    async *executeStream(input: { text: string }) {
      yield input.text;
      return input.text;
    }
  });

  const toolExecutor = new StreamingToolExecutor(registry, { progressChunkSize: 1 });

  const deps: QueryEngineDeps = {
    config: {
      runtime: { maxTurns: 3, maxToolCallsPerTurn: 3, enableStreamingTools: true },
      providers: {
        primary: { provider: 'custom', model: 'demo' },
        fallbacks: [],
        retry: { maxAttempts: 1, baseDelayMs: 1, maxDelayMs: 1, jitterRatio: 0 },
        circuitBreaker: { failureThreshold: 2, resetTimeoutMs: 10, halfOpenMaxRequests: 1 },
        rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
        observability: { debug: false },
        gracefulDegradationMessage: 'degraded',
        credentials: {}
      },
      rdt: { enabled: false, maxRecurrentSteps: 0 }
    },
    stateStore,
    toolExecutor,
    pickProviderPlan: async () => ({ primary: { provider: 'custom', model: 'demo', reason: 'test' }, fallbacks: [] }),
    executeModel: async function* (_input, session) {
      if (session.messages.some((m) => m.includes('toolCallId'))) {
        yield 'done';
        return 'done';
      }

      const call = '[[tool:stream_echo {"text":"ok"}]]';
      yield call;
      return call;
    }
  };

  const engine = new QueryEngineImpl(deps);
  const stream = engine.runTurn({ sessionId: 'integration-s', userMessage: 'go' });
  const eventTypes: EngineEvent['type'][] = [];
  for await (const event of stream) {
    eventTypes.push(event.type);
  }

  assert.ok(eventTypes.includes('tool_progress'));
  assert.ok(eventTypes.includes('tool_batch_completed'));
});
