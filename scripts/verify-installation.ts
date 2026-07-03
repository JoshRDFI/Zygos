#!/usr/bin/env tsx
import { access, mkdir, stat } from 'node:fs/promises';
import { constants as fsConstants } from 'node:fs';
import { dirname, resolve } from 'node:path';
import process from 'node:process';
import { loadConfig } from '../src/config/loader.js';
import { createEngine } from '../src/core/bootstrap.js';

function logStep(message: string): void {
  console.log(`\n[verify] ${message}`);
}

function pass(message: string): void {
  console.log(`[ok] ${message}`);
}

function fail(message: string): never {
  console.error(`[error] ${message}`);
  process.exitCode = 1;
  throw new Error(message);
}

async function checkNodeVersion(): Promise<void> {
  logStep('Checking Node.js version...');
  const [majorText] = process.versions.node.split('.');
  const major = Number(majorText);
  if (!Number.isFinite(major) || major < 20) {
    fail(`Node.js >= 20 is required. Found ${process.versions.node}`);
  }
  pass(`Node.js version is ${process.versions.node}`);
}

async function checkDependencies(): Promise<void> {
  logStep('Checking dependencies...');
  const cwd = process.cwd();
  const nodeModulesPath = resolve(cwd, 'node_modules');
  await access(nodeModulesPath, fsConstants.R_OK);

  const required = ['better-sqlite3', 'yaml', 'zod', 'tsx'];
  for (const pkg of required) {
    try {
      await import(pkg);
    } catch (error) {
      fail(`Missing or broken dependency: ${pkg}. Run npm install. (${String(error)})`);
    }
  }

  pass('Dependencies are installed and importable');
}

async function checkConfigValidation(): Promise<void> {
  logStep('Validating configuration...');
  const config = await loadConfig();

  if (!config.providers?.primary?.provider || !config.providers?.primary?.model) {
    fail('Primary provider configuration is missing');
  }

  pass(`Configuration loaded successfully (primary=${config.providers.primary.provider}:${config.providers.primary.model})`);
}

async function checkDatabasePaths(): Promise<void> {
  logStep('Checking database path readiness...');
  const contextDb = process.env.ZYGOS_CONTEXT_DB ?? '.zygos/context.db';
  const learningDb = process.env.ZYGOS_LEARNING_DB ?? '.zygos/learning.db';
  const interviewDb = process.env.ZYGOS_INTERVIEW_DB ?? contextDb;

  const paths = [contextDb, learningDb, interviewDb];

  for (const dbPath of paths) {
    const dir = dirname(resolve(process.cwd(), dbPath));
    await mkdir(dir, { recursive: true });
    await access(dir, fsConstants.W_OK);
  }

  pass('Database directories are writable');
}

async function smokeTestEngine(): Promise<void> {
  logStep('Running engine smoke test...');
  const sessionId = `verify_${Date.now()}`;
  const engine = await createEngine(undefined, { provider: 'custom', model: 'demo', rdtEnabled: false });

  let completed = false;
  for await (const event of engine.runTurn({
    sessionId,
    userMessage: 'Verification ping',
    mode: 'standard'
  })) {
    if (event.type === 'turn_completed') {
      completed = true;
      break;
    }
    if (event.type === 'turn_failed') {
      fail(`Smoke test turn failed: ${event.error.code} - ${event.error.message}`);
    }
  }

  if (!completed) {
    fail('Smoke test did not complete successfully');
  }

  const contextDb = resolve(process.cwd(), process.env.ZYGOS_CONTEXT_DB ?? '.zygos/context.db');
  const learningDb = resolve(process.cwd(), process.env.ZYGOS_LEARNING_DB ?? '.zygos/learning.db');

  const contextDbStat = await stat(contextDb);
  const learningDbStat = await stat(learningDb);

  if (!contextDbStat.isFile()) {
    fail(`Expected context DB file not found: ${contextDb}`);
  }
  if (!learningDbStat.isFile()) {
    fail(`Expected learning DB file not found: ${learningDb}`);
  }

  pass('Engine smoke test passed and SQLite databases initialized');
}

async function main(): Promise<void> {
  console.log('Zygos Installation Verification');
  await checkNodeVersion();
  await checkDependencies();
  await checkConfigValidation();
  await checkDatabasePaths();
  await smokeTestEngine();

  console.log('\n✅ System ready to run. Try: npm run dev -- "Hello Zygos"');
}

main().catch((error) => {
  console.error('\n❌ Verification failed.');
  if (error instanceof Error) {
    console.error(error.message);
  } else {
    console.error(String(error));
  }
  process.exitCode = 1;
});
