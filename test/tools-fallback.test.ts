import assert from 'node:assert/strict';
import test from 'node:test';
import { z } from 'zod';
import { BasicToolRegistry } from '../src/tools/registry.js';
import { StreamingToolExecutor } from '../src/tools/streaming-executor.js';

function createCtx() {
  return {
    sessionId: 's-test',
    turnId: 't-test',
    signal: new AbortController().signal,
    role: 'admin' as const
  };
}

function registerPair(registry: BasicToolRegistry, options: { backupFails?: boolean; backupFallback?: string } = {}) {
  registry.register({
    meta: {
      name: 'primary_tool',
      description: 'always fails',
      timeoutMs: 1_000,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 },
      fallbackTool: 'backup_tool'
    },
    inputSchema: z.object({ value: z.string() }),
    outputSchema: z.object({ echoed: z.string() }),
    async execute(): Promise<{ echoed: string }> {
      throw new Error('primary exploded');
    }
  });

  registry.register({
    meta: {
      name: 'backup_tool',
      description: 'fallback target',
      timeoutMs: 1_000,
      concurrency: 'safe_parallel',
      destructive: false,
      permission: 'allow',
      aliases: [],
      retry: { attempts: 1, backoffMs: 1 },
      fallbackTool: options.backupFallback
    },
    inputSchema: z.object({ value: z.string() }),
    outputSchema: z.object({ echoed: z.string() }),
    async execute(input: { value: string }): Promise<{ echoed: string }> {
      if (options.backupFails) {
        throw new Error('backup exploded too');
      }
      return { echoed: `backup:${input.value}` };
    }
  });
}

test('executor runs the configured fallback tool when the primary fails', async () => {
  const registry = new BasicToolRegistry();
  registerPair(registry);

  const executor = new StreamingToolExecutor(registry);
  const result = await executor.execute({ id: 'c1', name: 'primary_tool', input: { value: 'hi' } }, createCtx());

  assert.equal(result.ok, true);
  assert.deepEqual(result.output, { echoed: 'backup:hi' });
  assert.ok(
    result.warnings.some((warning) => warning.includes('fallback')),
    'result must disclose it came from a fallback tool'
  );
});

test('executor keeps the primary error when the fallback also fails, without looping', async () => {
  const registry = new BasicToolRegistry();
  // backup_tool falls back to primary_tool: a cycle that must not recurse.
  registerPair(registry, { backupFails: true, backupFallback: 'primary_tool' });

  const executor = new StreamingToolExecutor(registry);
  const result = await executor.execute({ id: 'c2', name: 'primary_tool', input: { value: 'hi' } }, createCtx());

  assert.equal(result.ok, false);
  assert.match(result.error ?? '', /primary exploded/);
});
