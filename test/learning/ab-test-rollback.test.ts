import test from 'node:test';
import assert from 'node:assert/strict';
import { z } from 'zod';
import { ToolModificationSystem } from '../../src/learning/modification.js';
import type { LearningRuntimeDeps, ToolModificationProposal } from '../../src/types/learning.types.js';
import type { ToolDefinition } from '../../src/types/tool.types.js';

function makeDefinition(version: string): ToolDefinition {
  return {
    meta: {
      name: 'flaky_sum',
      description: 'Adds numbers for A/B rollback test',
      version,
      timeoutMs: 20,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 }
    },
    inputSchema: z.object({ a: z.number(), b: z.number() }),
    outputSchema: z.object({ total: z.number() }),
    async execute(input: { a: number; b: number }) {
      return { total: input.a + input.b };
    }
  };
}

test('runABTest restores the baseline tool when candidate execution throws', async () => {
  const baseline = makeDefinition('1.0.0');
  const candidate = makeDefinition('1.0.1');
  let active: ToolDefinition = baseline;

  const runtime: LearningRuntimeDeps = {
    listTools: () => [active],
    getTool: () => active,
    registerTool: () => {},
    updateTool: (_name, definition) => {
      active = definition;
    },
    executeForLearning: async () => {
      if (active === candidate) {
        throw new Error('runtime crashed mid-test');
      }
      return {
        toolCallId: 'c1',
        ok: true,
        output: { total: 3 },
        durationMs: 1,
        synthetic: false,
        partial: false,
        warnings: []
      };
    }
  };

  const system = new ToolModificationSystem(runtime, {
    minObservationsForProposal: 1,
    minSuccessRateGain: 0,
    maxLatencyRegressionRatio: 0.5,
    abTestSampleSize: 3,
    maxResourceCostPerTestMs: 1000
  });

  const proposal: ToolModificationProposal = {
    type: 'modification',
    toolName: 'flaky_sum',
    baselineVersionId: 1,
    candidateDefinition: candidate,
    patch: { timeoutMs: 40 },
    expectedDelta: { successRateDelta: 0.02, latencyDeltaMs: 10, errorRateDelta: 0.02 },
    testPlan: {
      sampleCalls: [{ id: 'c1', name: 'flaky_sum', input: { a: 1, b: 2 } }],
      minImprovement: 0,
      maxRegressionTolerance: 0.5
    },
    explanation: 'rollback safety test'
  };

  await assert.rejects(() => system.runABTest(proposal), /runtime crashed mid-test/);
  assert.equal(active, baseline, 'baseline definition must be restored after a failed A/B test');
});
