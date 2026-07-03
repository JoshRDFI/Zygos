import test from 'node:test';
import assert from 'node:assert/strict';
import { RDTRuntime } from '../../src/reasoning/rdt-runtime.js';
import type { RDTConfig, RDTPromptRequest } from '../../src/types/rdt.types.js';

const config: RDTConfig = {
  enabled: true,
  profile: 'balanced',
  prelude: {
    enabled: true,
    temperature: 0.1,
    maxTokens: 256,
    systemInstruction: 'decompose'
  },
  recurrent: {
    enabled: true,
    temperature: 0.2,
    maxTokens: 256,
    minLoopIters: 1,
    maxLoopIters: 3,
    allowBacktracking: true,
    allowParallelPaths: true,
    systemInstruction: 'recur'
  },
  coda: {
    enabled: true,
    temperature: 0.1,
    maxTokens: 256,
    systemInstruction: 'finalize'
  },
  loop: {
    maxLoopIters: 3,
    minLoopIters: 1,
    maxRevisionDepth: 2
  },
  confidence: {
    thresholds: { earlyExit: 0.75, revise: 0.4, floor: 0.2 },
    adaptive: true,
    adaptUpDelta: 0.03,
    adaptDownDelta: 0.03,
    smoothingFactor: 0.4
  },
  attention: {
    defaultMode: 'auto',
    switchByTask: true,
    modeSwitchComplexityThreshold: 0.4,
    moe: {
      enabled: true,
      routedExperts: ['math', 'coding', 'planning'],
      sharedExperts: ['synthesis'],
      topK: 2,
      maxParallelExperts: 3,
      loadBalanceWindow: 6
    }
  },
  quality: {
    enableTraceLogging: true,
    preserveReasoningChain: true,
    computeAdaptive: true,
    enableMultiHop: true
  }
};

function responseFor(request: RDTPromptRequest): string {
  if (request.stage === 'prelude') {
    return JSON.stringify({
      summary: 'Break into steps.',
      decomposition: ['step one', 'step two', 'step three'],
      reasoning: ['init']
    });
  }
  if (request.stage === 'recurrent') {
    return JSON.stringify({
      summary: 'Therefore final answer uses step one, step two, step three.',
      decomposition: ['step one', 'step two', 'step three'],
      reasoning: ['iterate']
    });
  }
  return 'Final answer synthesized.';
}

test('RDTRuntime runs prelude->recurrent->coda and emits early-exit capable result', async () => {
  const progressEvents: string[] = [];
  const runtime = new RDTRuntime({
    config,
    emit: (event) => {
      progressEvents.push(event.type);
    },
    invoke: async function* (request) {
      yield responseFor(request);
      return responseFor(request);
    }
  });

  const result = await runtime.run({
    prompt: 'Solve this multi-step reasoning task.',
    context: ['older context']
  });

  assert.ok(result.finalText.length > 0);
  assert.ok(result.loopsUsed >= 1);
  assert.ok(result.finalConfidence > 0);
  assert.ok(progressEvents.includes('rdt_stage_started'));
  assert.ok(progressEvents.includes('rdt_iteration_completed'));
});
