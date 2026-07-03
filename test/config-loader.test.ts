import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { loadConfig } from '../src/config/loader.js';

test('loadConfig returns hardened defaults', async () => {
  const config = await loadConfig();
  assert.equal(config.providers.retry.maxAttempts > 0, true);
  assert.equal(config.providers.rateLimit.maxRequestsPerMinute > 0, true);
  assert.equal(typeof config.providers.observability.debug, 'boolean');
});

test('loadConfig defaults learning to human approval (never autonomous)', async () => {
  const config = await loadConfig();
  assert.equal(config.learning.autoApplyLowRisk, false);
  assert.equal(config.learning.approvalMode, 'manual');
});

test('loadConfig validates malformed fallback routes', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ghv2-'));
  const file = join(dir, 'config.yaml');
  await writeFile(
    file,
    `providers:\n  primary:\n    provider: openai\n    model: gpt-4o-mini\n  fallbacks:\n    - provider: openai\n      model: gpt-4o-mini\n`,
    'utf8'
  );

  await assert.rejects(async () => loadConfig(file), /Duplicate provider route detected/);
});

test('loadConfig migrates legacy provider block', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ghv2-'));
  const file = join(dir, 'legacy.json');
  await writeFile(
    file,
    JSON.stringify({
      provider: {
        primary: { provider: 'custom', model: 'demo', weight: 1 },
        fallbacks: []
      }
    }),
    'utf8'
  );

  const config = await loadConfig(file);
  assert.equal(config.providers.primary.provider, 'custom');
});
