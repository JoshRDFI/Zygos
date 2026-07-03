import test from 'node:test';
import assert from 'node:assert/strict';
import { ConfidenceEvaluator } from '../../src/reasoning/confidence.js';
import type { ConfidenceConfig } from '../../src/types/rdt.types.js';

const config: ConfidenceConfig = {
  thresholds: { earlyExit: 0.8, revise: 0.5, floor: 0.2 },
  adaptive: true,
  adaptUpDelta: 0.05,
  adaptDownDelta: 0.05,
  smoothingFactor: 0.5
};

test('ConfidenceEvaluator computes metrics and adapts threshold', () => {
  const evaluator = new ConfidenceEvaluator(config);

  const first = evaluator.evaluate('Therefore final answer is to compare two options and conclude.', undefined, ['compare options']);
  assert.ok(first.confidence > 0.4);

  const second = evaluator.evaluate(
    'Therefore final answer is to compare two options with conclusion and result.',
    {
      iteration: 1,
      summary: 'compare options',
      reasoning: [],
      confidence: first.confidence,
      confidenceThreshold: first.threshold,
      attentionMode: 'mla',
      routedExperts: [],
      sharedExperts: [],
      quality: first.metrics
    },
    ['compare options']
  );

  assert.ok(second.confidence >= first.confidence - 0.05);
  assert.ok(evaluator.getHistory().length === 2);
  assert.ok(evaluator.getAdaptiveThreshold() >= config.thresholds.floor);
});
