import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { Interviewer } from '../src/interviewer/interviewer.js';

test('interviewer records a session warning when askProvider fails instead of swallowing it', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'ghv2-interview-warn-'));
  const interviewer = new Interviewer({
    dbPath: join(dir, 'interview.sqlite'),
    config: {
      enabled: true,
      requireForComplexBuilds: true,
      complexityThreshold: 2,
      maxQuestions: 6,
      allowBypassForSimpleRequests: true,
      allowOverrideByFlag: true,
      template: 'auto'
    },
    askProvider: async () => {
      throw new Error('provider auth failed');
    }
  });
  await interviewer.init();

  try {
    const response = await interviewer.start({ sessionId: 's-warn', title: 'API for orders' });

    // graceful degradation must be preserved: interview continues with the base question
    assert.equal(response.done, false);
    assert.ok(response.nextQuestion?.text);

    // ...but the failure must be visible on the persisted session, not swallowed
    const session = await interviewer.getSession('s-warn');
    assert.ok(session);
    assert.ok(
      session?.providerWarnings?.some((warning) => warning.includes('provider auth failed')),
      'session must record why the provider-generated question was unavailable'
    );
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
