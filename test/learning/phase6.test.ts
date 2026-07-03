import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { z } from 'zod';
import { BasicToolRegistry } from '../../src/tools/registry.js';
import { ToolExecutor } from '../../src/tools/executor.js';
import { LearningManager } from '../../src/learning/manager.js';

async function withLearningManager(run: (manager: LearningManager, registry: BasicToolRegistry) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), 'gh-learning-'));
  const dbPath = join(dir, 'learning.sqlite');

  const registry = new BasicToolRegistry();
  registry.register({
    meta: {
      name: 'flaky_sum',
      description: 'Adds numbers but can fail for test',
      version: '1.0.0',
      timeoutMs: 20,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 }
    },
    inputSchema: z.object({ a: z.number(), b: z.number(), fail: z.boolean().optional() }),
    outputSchema: z.object({ total: z.number() }),
    async execute(input) {
      if (input.fail) {
        throw new Error('simulated failure');
      }
      await new Promise((resolve) => setTimeout(resolve, 2));
      return { total: input.a + input.b };
    }
  });

  const executor = new ToolExecutor(registry);
  const manager = new LearningManager({
    dbPath,
    config: {
      enabled: true,
      approvalMode: 'auto',
      autoApplyLowRisk: true,
      maxProposalsPerCycle: 5,
      minObservationsForProposal: 3,
      observeWindowSize: 50,
      maxModificationsPerHour: 20,
      maxToolCreationsPerDay: 20,
      abTestSampleSize: 3,
      maxLatencyRegressionRatio: 0.5,
      minSuccessRateGain: 0,
      maxResourceCostPerTestMs: 1000
    },
    runtime: {
      listTools: () => registry.list(),
      getTool: (name) => registry.getByName(name),
      registerTool: (definition) => registry.register(definition),
      updateTool: (name, definition) => registry.update?.(name, definition),
      removeTool: (name) => registry.remove?.(name),
      executeForLearning: async (call) =>
        executor.execute(call, {
          sessionId: 'learning-s',
          turnId: 'learning-t',
          signal: new AbortController().signal,
          role: 'system'
        })
    }
  });

  await manager.init();

  try {
    await run(manager, registry);
  } finally {
    await manager.close();
    await rm(dir, { recursive: true, force: true });
  }
}

test('learning manager records observations and generates proposals', async () => {
  await withLearningManager(async (manager) => {
    for (let i = 0; i < 4; i += 1) {
      await manager.observeToolExecution({
        sessionId: 's1',
        turnId: `t${i}`,
        call: { id: `c${i}`, name: 'flaky_sum', input: { a: 1, b: 2, fail: i % 2 === 0 } },
        result: {
          toolCallId: `c${i}`,
          ok: i % 2 !== 0,
          output: i % 2 !== 0 ? { total: 3 } : undefined,
          error: i % 2 === 0 ? 'simulated failure' : undefined,
          normalizedError: i % 2 === 0 ? { code: 'simulated', message: 'simulated failure', retryable: true } : undefined,
          durationMs: i % 2 === 0 ? 30 : 3,
          synthetic: false,
          partial: false,
          warnings: []
        }
      });
    }

    const cycle = await manager.runCycle('test');
    assert.ok(cycle.proposals.length >= 1);

    const proposals = await manager.listProposals();
    assert.ok(proposals.length >= 1);
  });
});

test('learning manager can rollback modified tool to previous version', async () => {
  await withLearningManager(async (manager, registry) => {
    for (let i = 0; i < 5; i += 1) {
      await manager.observeToolExecution({
        sessionId: 's2',
        turnId: `t${i}`,
        call: { id: `c${i}`, name: 'flaky_sum', input: { a: 1, b: 2, fail: true } },
        result: {
          toolCallId: `c${i}`,
          ok: false,
          error: 'simulated failure',
          normalizedError: { code: 'simulated', message: 'simulated failure', retryable: true },
          durationMs: 20,
          synthetic: false,
          partial: false,
          warnings: []
        }
      });
    }

    const cycle = await manager.runCycle('test');
    const modProposal = cycle.proposals.find((proposal) => proposal.kind === 'modification');
    assert.ok(modProposal);

    if (modProposal) {
      await manager.applyProposal(modProposal.id, 'test');
      const beforeRollback = registry.getByName('flaky_sum');
      assert.ok(beforeRollback);
      await manager.rollbackTool('flaky_sum');
      const afterRollback = registry.getByName('flaky_sum');
      assert.ok(afterRollback);
      assert.equal(afterRollback?.meta.name, 'flaky_sum');
    }
  });
});
