import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { Interviewer } from '../src/interviewer/interviewer.js';
import { BuildPlanGenerator } from '../src/interviewer/plan-generator.js';
import { QueryEngineImpl } from '../src/core/engine.js';
import { InMemoryStateStore } from '../src/core/state.js';
import type { InterviewSession } from '../src/types/interviewer.types.js';
import type { QueryEngineDeps } from '../src/types/core.types.js';

async function withInterviewer(run: (interviewer: Interviewer, dbPath: string) => Promise<void>): Promise<void> {
  const dir = await mkdtemp(join(tmpdir(), 'ghv2-interview-'));
  const dbPath = join(dir, 'interview.sqlite');
  const interviewer = new Interviewer({
    dbPath,
    config: {
      enabled: true,
      requireForComplexBuilds: true,
      complexityThreshold: 2,
      maxQuestions: 6,
      allowBypassForSimpleRequests: true,
      allowOverrideByFlag: true,
      template: 'auto'
    }
  });
  await interviewer.init();

  try {
    await run(interviewer, dbPath);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

test('BuildPlanGenerator creates roadmap and markdown export', () => {
  const session: InterviewSession = {
    id: 's-plan',
    status: 'active',
    projectType: 'api_service',
    startedAt: Date.now(),
    updatedAt: Date.now(),
    stakeholderIds: ['pm'],
    turns: [
      { id: 'q1', role: 'interviewer', content: 'What should API do?', timestamp: Date.now(), question: { id: 'q1', text: 'What should API do?', category: 'goals', askedAt: Date.now() } },
      { id: 'a1', role: 'stakeholder', content: 'Must provide authenticated endpoints for order status and support 500 rpm.', timestamp: Date.now() },
      { id: 'a2', role: 'stakeholder', content: 'Integrate with payment gateway and ERP, with retry and audit trail.', timestamp: Date.now() }
    ],
    extractedRequirements: [],
    answeredQuestionIds: ['q1'],
    pendingQuestionIds: [],
    askedClarificationCount: 0,
    maxQuestions: 6,
    complexitySignal: 2,
    scopeCreepSignal: 0
  };

  const generator = new BuildPlanGenerator();
  const plan = generator.generate(session);
  const exported = generator.export(plan);

  assert.ok(plan.roadmap.length >= 3);
  assert.ok(plan.estimatedEffortHours > 0);
  assert.match(exported.markdown, /Roadmap/);
});

test('Interviewer supports multi-turn interview and persists plan', async () => {
  await withInterviewer(async (interviewer) => {
    const start = await interviewer.start({ sessionId: 's1', title: 'Build web app for internal analytics', stakeholderId: 'pm' });
    assert.ok(start.nextQuestion);

    let response = await interviewer.answer('s1', 'We need dashboards for sales and customer churn with SSO and role-based access.', 'pm');
    response = await interviewer.answer('s1', 'Must deploy in our private cloud and meet SOC2 logging standards.', 'security');
    response = await interviewer.answer('s1', 'Timeline is six weeks with weekly milestones and UAT.', 'pm');
    response = await interviewer.answer('s1', 'Integrate with CRM and billing APIs.', 'eng');
    response = await interviewer.answer('s1', 'MVP includes auth, dashboard, filters, and export.', 'pm');

    assert.equal(response.done, true);
    assert.ok(response.generatedPlan);

    const exported = await interviewer.exportPlan('s1');
    assert.ok(exported);
    assert.match(exported?.markdown ?? '', /Build Plan/);

    const metrics = interviewer.getMetrics();
    assert.ok(metrics.sessionsStarted >= 1);
    assert.ok(metrics.sessionsCompleted >= 1);
  });
});

test('QueryEngine interview mode gates complex builds and emits interview events', async () => {
  await withInterviewer(async (interviewer) => {
    const deps: QueryEngineDeps = {
      config: {
        runtime: { maxTurns: 2, maxToolCallsPerTurn: 2, enableStreamingTools: false },
        providers: {
          primary: { provider: 'custom', model: 'demo', weight: 1 },
          fallbacks: [],
          retry: { maxAttempts: 1, baseDelayMs: 1, maxDelayMs: 1, jitterRatio: 0 },
          circuitBreaker: { failureThreshold: 2, resetTimeoutMs: 10, halfOpenMaxRequests: 1 },
          rateLimit: { maxRequestsPerMinute: 100, burst: 100 },
          observability: { debug: false },
          gracefulDegradationMessage: 'degraded',
          credentials: {}
        },
        rdt: {
          enabled: false,
          profile: 'balanced',
          prelude: { enabled: true, temperature: 0.1, maxTokens: 128, systemInstruction: 'x' },
          recurrent: {
            enabled: true,
            temperature: 0.2,
            maxTokens: 128,
            minLoopIters: 1,
            maxLoopIters: 1,
            allowBacktracking: false,
            allowParallelPaths: false,
            systemInstruction: 'x'
          },
          coda: { enabled: true, temperature: 0.1, maxTokens: 128, systemInstruction: 'x' },
          loop: { maxLoopIters: 1, minLoopIters: 1, maxRevisionDepth: 1 },
          confidence: {
            thresholds: { earlyExit: 0.8, revise: 0.5, floor: 0.2 },
            adaptive: true,
            adaptUpDelta: 0.03,
            adaptDownDelta: 0.03,
            smoothingFactor: 0.5
          },
          attention: {
            defaultMode: 'auto',
            switchByTask: true,
            modeSwitchComplexityThreshold: 0.5,
            moe: {
              enabled: true,
              routedExperts: ['coding'],
              sharedExperts: ['synthesis'],
              topK: 1,
              maxParallelExperts: 1,
              loadBalanceWindow: 3
            }
          },
          quality: {
            enableTraceLogging: false,
            preserveReasoningChain: true,
            computeAdaptive: true,
            enableMultiHop: false
          }
        },
        learning: {
          enabled: false,
          approvalMode: 'manual',
          autoApplyLowRisk: false,
          maxProposalsPerCycle: 1,
          minObservationsForProposal: 3,
          observeWindowSize: 20,
          maxModificationsPerHour: 2,
          maxToolCreationsPerDay: 2,
          abTestSampleSize: 3,
          maxLatencyRegressionRatio: 0.2,
          minSuccessRateGain: 0.03,
          maxResourceCostPerTestMs: 1000
        },
        interview: {
          enabled: true,
          requireForComplexBuilds: true,
          complexityThreshold: 1,
          maxQuestions: 6,
          allowBypassForSimpleRequests: true,
          allowOverrideByFlag: true,
          template: 'auto'
        }
      },
      stateStore: new InMemoryStateStore(),
      interviewer,
      toolExecutor: {
        async executeBatch() {
          return [];
        }
      },
      pickProviderPlan: async () => ({ primary: { provider: 'custom', model: 'demo', reason: 'test' }, fallbacks: [] }),
      executeModel: async function* () {
        yield 'model output';
        return 'model output';
      }
    };

    const engine = new QueryEngineImpl(deps);
    const events = [] as string[];
    for await (const event of engine.runTurn({
      sessionId: 'gated1',
      userMessage: 'Design a secure multi-tenant API platform with integrations and compliance requirements',
      mode: 'standard'
    })) {
      events.push(event.type);
    }

    assert.ok(events.includes('interview_progress'));
    assert.ok(events.includes('turn_completed'));
  });
});
