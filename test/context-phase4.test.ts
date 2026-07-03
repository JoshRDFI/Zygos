import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { QueryEngineImpl } from '../src/core/engine.js';
import { InMemoryStateStore } from '../src/core/state.js';
import { TokenBudgetSystem } from '../src/context/budget.js';
import { ContextCompactor } from '../src/context/compaction.js';
import { ContextManager } from '../src/context/manager.js';
import { SQLiteContextStorage } from '../src/context/storage.js';
import type { QueryEngineDeps } from '../src/types/core.types.js';
import type { ContextTurn } from '../src/types/context.types.js';

async function withTempStorage<T>(fn: (storage: SQLiteContextStorage, dbPath: string) => Promise<T>): Promise<T> {
  const dir = await mkdtemp(join(tmpdir(), 'gh-context-'));
  const dbPath = join(dir, 'context.sqlite');
  const storage = new SQLiteContextStorage({ dbPath, readPoolSize: 1 });
  await storage.init();

  try {
    return await fn(storage, dbPath);
  } finally {
    await storage.close();
    await rm(dir, { recursive: true, force: true });
  }
}

function makeTurn(partial: Partial<ContextTurn> & Pick<ContextTurn, 'id' | 'sessionId' | 'turnIndex' | 'speaker' | 'contentType' | 'content'>): ContextTurn {
  const now = Date.now();
  return {
    ...partial,
    id: partial.id,
    sessionId: partial.sessionId,
    turnIndex: partial.turnIndex,
    speaker: partial.speaker,
    contentType: partial.contentType,
    content: partial.content,
    createdAt: partial.createdAt ?? now,
    updatedAt: partial.updatedAt ?? now,
    importanceScore: partial.importanceScore ?? 0.6,
    tags: partial.tags ?? [],
    piiDetected: partial.piiDetected ?? false,
    isCompacted: partial.isCompacted ?? false,
    tokenUsage: partial.tokenUsage ?? {
      inputTokens: 10,
      outputTokens: 8,
      totalTokens: 18,
      estimated: true
    }
  };
}

test('sqlite storage persists turns and supports FTS search', async () => {
  await withTempStorage(async (storage) => {
    await storage.upsertSession('s1', 'session');
    await storage.saveTurns([
      makeTurn({ id: 't1', sessionId: 's1', turnIndex: 0, speaker: 'user', contentType: 'message', content: 'hello budget planning' }),
      makeTurn({ id: 't2', sessionId: 's1', turnIndex: 1, speaker: 'assistant', contentType: 'message', content: 'we should compact context window' })
    ]);

    const recent = await storage.getRecentTurns('s1', 5);
    assert.equal(recent.length, 2);

    const hits = await storage.searchTurns({ sessionId: 's1', query: 'compact OR budget', includeSnippets: true });
    assert.ok(hits.length >= 1);
    assert.match(hits[0]?.turn.content ?? '', /compact|budget/);
  });
});

test('token budget calculates plan and report with overflow risk', () => {
  const budget = new TokenBudgetSystem();
  const plan = budget.plan({ maxContextTokens: 1000, reserveOutputTokens: 200, reserveToolTokens: 100, strategy: 'priority_based' });
  assert.equal(plan.hardLimitTokens, 1000);

  const turns = [
    makeTurn({ id: 'a', sessionId: 's', turnIndex: 0, speaker: 'user', contentType: 'message', content: 'x'.repeat(800) }),
    makeTurn({ id: 'b', sessionId: 's', turnIndex: 1, speaker: 'assistant', contentType: 'message', content: 'y'.repeat(800) })
  ];
  const window = budget.buildWindow('model', plan, budget.estimateTurns(turns));
  const report = budget.createReport('s', turns, window);
  assert.ok(['low', 'medium', 'high'].includes(report.overflowRisk));
});

test('compaction preserves tool results and creates summary turn', async () => {
  const budget = new TokenBudgetSystem();
  const compactor = new ContextCompactor(budget);

  const turns: ContextTurn[] = [
    makeTurn({
      id: 'u1',
      sessionId: 's2',
      turnIndex: 0,
      speaker: 'user',
      contentType: 'message',
      content: 'my name is alex and i prefer sqlite backups',
      tokenUsage: { inputTokens: 30, outputTokens: 20, totalTokens: 50, estimated: false }
    }),
    makeTurn({
      id: 'a1',
      sessionId: 's2',
      turnIndex: 1,
      speaker: 'assistant',
      contentType: 'message',
      content: 'acknowledged. we can do that.',
      tokenUsage: { inputTokens: 24, outputTokens: 24, totalTokens: 48, estimated: false }
    }),
    makeTurn({
      id: 'tool',
      sessionId: 's2',
      turnIndex: 2,
      speaker: 'tool',
      contentType: 'tool_result',
      content: '{"status":"ok"}',
      toolName: 'backup',
      tokenUsage: { inputTokens: 20, outputTokens: 20, totalTokens: 40, estimated: false }
    }),
    makeTurn({
      id: 'a2',
      sessionId: 's2',
      turnIndex: 3,
      speaker: 'assistant',
      contentType: 'message',
      content: 'x'.repeat(1200),
      tokenUsage: { inputTokens: 220, outputTokens: 220, totalTokens: 440, estimated: false }
    })
  ];

  const result = await compactor.compact({
    sessionId: 's2',
    turns,
    maxTokens: 120,
    strategy: {
      type: 'hierarchical',
      targetReductionRatio: 0.6,
      preserveToolPairs: true,
      preserveTaggedTurns: false,
      preserveRecentTurns: 1,
      maxSummaryTokens: 120
    }
  });

  assert.equal(result.compacted, true);
  assert.ok(result.summaryTurn);
  assert.equal(result.removedTurnIds.includes('tool'), false);
});

test('context manager and query engine integrate for automatic turn storage and search', async () => {
  await withTempStorage(async (storage) => {
    const manager = new ContextManager(storage, { defaultModelContextTokens: 2000 });
    const stateStore = new InMemoryStateStore();

    const deps: QueryEngineDeps = {
      config: {
        runtime: { maxTurns: 2, maxToolCallsPerTurn: 2, enableStreamingTools: true },
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
      contextManager: manager,
      toolExecutor: {
        async executeBatch() {
          return [];
        }
      },
      pickProviderPlan: async () => ({ primary: { provider: 'custom', model: 'demo', reason: 'test' }, fallbacks: [] }),
      executeModel: async function* () {
        yield 'hello from assistant';
        return 'hello from assistant';
      }
    };

    const engine = new QueryEngineImpl(deps);
    for await (const _event of engine.runTurn({ sessionId: 's-search', userMessage: 'remember that i prefer concise output' })) {
      // consume events
    }

    const hits = await engine.searchHistory?.({ sessionId: 's-search', query: 'prefer concise', includeSnippets: true });
    assert.ok((hits?.length ?? 0) >= 1);

    const snapshot = await manager.getSnapshot('s-search');
    assert.ok(snapshot);
    assert.ok((snapshot?.memory.length ?? 0) >= 1);
  });
});
