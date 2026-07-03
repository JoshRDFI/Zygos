import test from 'node:test';
import assert from 'node:assert/strict';
import { ProviderRouterImpl } from '../src/providers/router.js';
import { MockProvider } from './helpers/mock-provider.js';
import type { ProviderPlan } from '../src/types/provider.types.js';

function makeRouter() {
  const primary = new MockProvider('openai', { enabled: true, apiKey: 'test', models: ['gpt'], weight: 1 }, {
    failAttempts: 2,
    responseText: 'primary-ok'
  });
  const fallback = new MockProvider('anthropic', { enabled: true, apiKey: 'test', models: ['claude'], weight: 1 }, {
    responseText: 'fallback-ok'
  });

  return {
    primary,
    fallback,
    router: new ProviderRouterImpl([primary, fallback], {
      retry: { maxAttempts: 2, baseDelayMs: 1, maxDelayMs: 2, jitterRatio: 0 },
      circuitBreaker: { failureThreshold: 1, resetTimeoutMs: 10_000, halfOpenMaxRequests: 1 },
      rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
      observability: { debug: false },
      gracefulDegradationMessage: 'degraded'
    })
  };
}

function plan(): ProviderPlan {
  return {
    primary: { provider: 'openai', model: 'gpt-4o-mini', reason: 'primary' },
    fallbacks: [{ provider: 'anthropic', model: 'claude-3-5-haiku-latest', reason: 'fallback' }]
  };
}

test('router fallback activates after retries exhausted', async () => {
  const { router } = makeRouter();
  const selected: string[] = [];
  const stream = router.streamWithFallback(
    { sessionId: 's1', userMessage: 'hello' },
    [{ role: 'user', content: 'hello' }],
    plan(),
    async (event) => {
      if (event.type === 'provider_selected') {
        selected.push(`${event.route.provider}:${event.route.model}`);
      }
    }
  );

  let result = '';
  for await (const chunk of stream) {
    result += chunk;
  }

  assert.equal(result, 'fallback-ok');
  assert.deepEqual(selected, ['openai:gpt-4o-mini', 'anthropic:claude-3-5-haiku-latest']);
});

test('router plan excludes unsupported models', async () => {
  const unsupported = new MockProvider('openai', { enabled: true, apiKey: 'test', models: ['gpt'] }, {
    unsupportedModels: ['bad-model']
  });
  const good = new MockProvider('anthropic', { enabled: true, apiKey: 'test', models: ['claude'] });
  const router = new ProviderRouterImpl([unsupported, good], {
    retry: { maxAttempts: 1, baseDelayMs: 1, maxDelayMs: 1, jitterRatio: 0 },
    circuitBreaker: { failureThreshold: 1, resetTimeoutMs: 1000, halfOpenMaxRequests: 1 },
    rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
    observability: { debug: false }
  });

  const planned = await router.plan({
    userInput: { sessionId: 's2', userMessage: 'hello' },
    routes: [
      { provider: 'openai', model: 'bad-model', reason: 'bad' },
      { provider: 'anthropic', model: 'claude-3-5-haiku-latest', reason: 'good' }
    ]
  });

  assert.equal(planned.primary.provider, 'anthropic');
});

test('router opens circuit breaker after repeated failures', async () => {
  const failing = new MockProvider('openai', { enabled: true, apiKey: 'test', models: ['gpt'] }, { failAttempts: 10 });
  const backup = new MockProvider('anthropic', { enabled: true, apiKey: 'test', models: ['claude'] }, { responseText: 'ok' });

  const router = new ProviderRouterImpl([failing, backup], {
    retry: { maxAttempts: 1, baseDelayMs: 1, maxDelayMs: 1, jitterRatio: 0 },
    circuitBreaker: { failureThreshold: 1, resetTimeoutMs: 10_000, halfOpenMaxRequests: 1 },
    rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
    observability: { debug: false }
  });

  const run = router.streamWithFallback(
    { sessionId: 's-breaker', userMessage: 'hello' },
    [{ role: 'user', content: 'hello' }],
    plan(),
    async () => {}
  );

  let out = '';
  for await (const chunk of run) {
    out += chunk;
  }

  assert.equal(out, 'ok');
  assert.equal(failing.attempts, 1);
});

test('router returns graceful degradation message when all providers fail', async () => {
  const failingOpenAI = new MockProvider('openai', { enabled: true, apiKey: 'test', models: ['gpt'] }, {
    failAttempts: 10
  });
  const failingAnthropic = new MockProvider('anthropic', { enabled: true, apiKey: 'test', models: ['claude'] }, {
    failAttempts: 10
  });

  const router = new ProviderRouterImpl([failingOpenAI, failingAnthropic], {
    retry: { maxAttempts: 1, baseDelayMs: 1, maxDelayMs: 1, jitterRatio: 0 },
    circuitBreaker: { failureThreshold: 1, resetTimeoutMs: 1000, halfOpenMaxRequests: 1 },
    rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
    observability: { debug: false },
    gracefulDegradationMessage: 'degraded message'
  });

  const stream = router.streamWithFallback(
    { sessionId: 's3', userMessage: 'hello' },
    [{ role: 'user', content: 'hello' }],
    plan(),
    async () => {}
  );

  let output = '';
  let doneValue: string | undefined;
  while (true) {
    const next = await stream.next();
    if (next.done) {
      doneValue = next.value;
      break;
    }
    output += next.value;
  }

  assert.equal(output, '');
  assert.equal(doneValue, 'degraded message');
});
