import test from 'node:test';
import assert from 'node:assert/strict';
import { AttentionMoEManager } from '../../src/reasoning/attention.js';
import type { AttentionConfig } from '../../src/types/rdt.types.js';

const config: AttentionConfig = {
  defaultMode: 'auto',
  switchByTask: true,
  modeSwitchComplexityThreshold: 0.5,
  moe: {
    enabled: true,
    routedExperts: ['math', 'coding', 'planning'],
    sharedExperts: ['synthesis', 'verification'],
    topK: 2,
    maxParallelExperts: 3,
    loadBalanceWindow: 5
  }
};

test('AttentionMoEManager routes experts and returns compute allocation', () => {
  const manager = new AttentionMoEManager(config);

  const decision = manager.decide({
    prompt: 'Analyze and compare multi step coding and math tradeoffs',
    decomposition: ['analyze coding', 'compare math tradeoffs', 'synthesize recommendation'],
    iteration: 1
  });

  assert.ok(decision.mode === 'mla' || decision.mode === 'gqa');
  assert.ok(decision.computeFraction > 0);
  assert.ok(decision.routedExperts.length > 0);
  assert.ok(Object.keys(manager.snapshotLoads()).length > 0);
});
