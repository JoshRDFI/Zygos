import test from 'node:test';
import assert from 'node:assert/strict';
import { estimateRequestTokens, enforceTokenBudget, trackContextWindow } from '../src/providers/tokens.js';
import { MockProvider } from './helpers/mock-provider.js';

test('token estimation caches repeated requests', () => {
  const provider = new MockProvider('custom', { enabled: true });
  const messages = [{ role: 'user' as const, content: 'hello world' }];

  const first = estimateRequestTokens(provider, 'model-a', messages);
  const second = estimateRequestTokens(provider, 'model-a', messages);

  assert.deepEqual(first, second);
});

test('budget enforcement rejects over-budget estimates', () => {
  const result = enforceTokenBudget(
    {
      promptTokens: 500,
      maxOutputTokens: 500,
      totalEstimate: 1000,
      modelContextWindow: 8192
    },
    {
      maxInputTokens: 200,
      maxOutputTokens: 600,
      maxTotalTokens: 1200
    }
  );

  assert.equal(result.allowed, false);
  assert.match(result.reason ?? '', /Input token estimate/);
});

test('context window tracking computes remaining tokens', () => {
  const state = trackContextWindow(
    {
      promptTokens: 200,
      maxOutputTokens: 100,
      totalEstimate: 300,
      modelContextWindow: 1000
    },
    150,
    'model-x'
  );

  assert.equal(state.remainingTokens, 650);
  assert.equal(state.model, 'model-x');
});
