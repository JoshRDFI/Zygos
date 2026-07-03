import test from 'node:test';
import assert from 'node:assert/strict';
import { BuildPlanGenerator } from '../src/interviewer/plan-generator.js';
import type { InterviewSession } from '../src/types/interviewer.types.js';

test('plan markdown export includes unresolved questions', () => {
  const now = Date.now();
  const session: InterviewSession = {
    id: 's-unresolved',
    status: 'active',
    projectType: 'api_service',
    startedAt: now,
    updatedAt: now,
    stakeholderIds: ['pm'],
    turns: [
      {
        id: 'q1',
        role: 'interviewer',
        content: 'What is the expected request volume?',
        timestamp: now,
        question: { id: 'q1', text: 'What is the expected request volume?', category: 'scope', askedAt: now }
      },
      { id: 'a1', role: 'stakeholder', content: 'We need authenticated order-status endpoints.', timestamp: now },
      {
        id: 'q2',
        role: 'interviewer',
        content: 'Which compliance regimes apply?',
        timestamp: now,
        question: { id: 'q2', text: 'Which compliance regimes apply?', category: 'constraints', askedAt: now }
      }
    ],
    extractedRequirements: [],
    answeredQuestionIds: ['q1'],
    pendingQuestionIds: [],
    askedClarificationCount: 0,
    maxQuestions: 6,
    complexitySignal: 1,
    scopeCreepSignal: 0
  };

  const generator = new BuildPlanGenerator();
  const plan = generator.generate(session);

  assert.ok(plan.unresolvedQuestions.length > 0, 'plan JSON should carry unresolved questions');

  const { markdown } = generator.export(plan);
  assert.ok(markdown.includes('Unresolved Questions'), 'markdown must have an Unresolved Questions section');
  assert.ok(markdown.includes('Which compliance regimes apply?'), 'markdown must list the open question');
});
