import { assertTransition, nextStateAfterModel } from './lifecycle.js';
import type {
  EngineEvent,
  ZygosError,
  QueryEngine,
  QueryEngineDeps,
  QuerySessionState,
  QueryState,
  TurnResult,
  UserTurnInput
} from '../types/core.types.js';
import type { ToolCall, ToolResult } from '../types/tool.types.js';

function createTurnId(): string {
  return `turn_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function parseToolCalls(text: string): ToolCall[] {
  const pattern = /\[\[tool:([a-zA-Z0-9_.-]+)\s+(\{[\s\S]*?\})\]\]/g;
  const calls: ToolCall[] = [];
  for (const match of text.matchAll(pattern)) {
    try {
      calls.push({
        id: `tool_${Math.random().toString(36).slice(2, 10)}`,
        name: match[1],
        input: JSON.parse(match[2]) as Record<string, unknown>
      });
    } catch {
      // Ignore malformed tool directives.
    }
  }
  return calls;
}

export class QueryEngineImpl implements QueryEngine {
  constructor(private readonly deps: QueryEngineDeps) {}

  async *runTurn(input: UserTurnInput): AsyncGenerator<EngineEvent, TurnResult, void> {
    const turnId = createTurnId();
    const now = Date.now();

    if (this.deps.interviewer) {
      const isInterviewMode = input.mode === 'interview';
      const allowOverride = this.deps.config.interview.allowOverrideByFlag && input.interview?.overrideGating === true;
      const gating = await this.deps.interviewer.shouldGateBuild(input.userMessage);

      if (isInterviewMode || (gating.gated && !allowOverride)) {
        const action = input.interview?.action ?? (isInterviewMode ? 'answer' : 'start');
        let response;
        if (action === 'start') {
          response = await this.deps.interviewer.start({
            sessionId: input.sessionId,
            title: input.userMessage,
            stakeholderId: input.interview?.stakeholderId
          });
        } else if (action === 'complete') {
          const plan = await this.deps.interviewer.complete(input.sessionId);
          const session = await this.deps.interviewer.getSession(input.sessionId);
          if (!session) {
            throw this.error('fatal_runtime_error', `No interview session found for ${input.sessionId}`);
          }
          response = { session, done: true, generatedPlan: plan ?? undefined };
        } else if (action === 'status') {
          const session = await this.deps.interviewer.getSession(input.sessionId);
          response = session
            ? { session, done: session.status === 'completed' }
            : await this.deps.interviewer.start({ sessionId: input.sessionId, title: input.userMessage });
        } else if (action === 'plan_export') {
          const session = await this.deps.interviewer.getSession(input.sessionId);
          if (!session) {
            response = await this.deps.interviewer.start({ sessionId: input.sessionId, title: input.userMessage });
          } else {
            const plan = await this.deps.interviewer.getPlan(input.sessionId);
            response = { session, done: session.status === 'completed', generatedPlan: plan ?? undefined };
          }
        } else {
          response = await this.deps.interviewer.answer(input.sessionId, input.userMessage, input.interview?.stakeholderId);
        }

        const interviewEvent: EngineEvent = { type: 'interview_progress', response };
        await this.emit(input.sessionId, interviewEvent);
        yield interviewEvent;

        if (response.generatedPlan) {
          const planEvent: EngineEvent = {
            type: 'interview_plan_generated',
            planId: response.generatedPlan.id,
            complexity: response.generatedPlan.complexity,
            estimatedEffortHours: response.generatedPlan.estimatedEffortHours
          };
          await this.emit(input.sessionId, planEvent);
          yield planEvent;
        }

        const metricsEvent: EngineEvent = { type: 'interview_metrics', metrics: this.deps.interviewer.getMetrics() };
        await this.emit(input.sessionId, metricsEvent);
        yield metricsEvent;

        const planExport = input.interview?.action === 'plan_export' ? await this.deps.interviewer.exportPlan(input.sessionId) : undefined;
        const result: TurnResult = {
          sessionId: input.sessionId,
          turnId,
          finalText: response.nextQuestion?.text ?? response.generatedPlan?.summary ?? 'Interview step completed.',
          tools: [],
          state: 'IDLE',
          usage: {
            inputChars: input.userMessage.length,
            outputChars: (response.nextQuestion?.text ?? response.generatedPlan?.summary ?? '').length
          },
          interview: {
            response,
            plan: response.generatedPlan,
            planExport: planExport ?? undefined
          }
        };
        if (this.deps.contextManager) {
          await this.deps.contextManager.postTurnUpdate({
            sessionId: input.sessionId,
            turnId,
            inputMessage: input.userMessage,
            assistantMessage: result.finalText,
            result,
            startedAt: now,
            completedAt: Date.now()
          });
        }

        const doneEvent: EngineEvent = { type: 'turn_completed', result };
        await this.emit(input.sessionId, doneEvent);
        yield doneEvent;
        return result;
      }
    }

    const plan = await this.deps.pickProviderPlan(input);

    const preparedContext = this.deps.contextManager ? await this.deps.contextManager.prepare(input, plan.primary.model) : null;

    const session: QuerySessionState = {
      sessionId: input.sessionId,
      turnId,
      state: 'IDLE',
      iteration: 0,
      activeProvider: plan.primary,
      providerPlan: plan,
      fallbackDepth: 0,
      messages: [...(preparedContext?.selectedTurns.map((turn) => turn.content) ?? []), input.userMessage],
      pendingTools: [],
      outputBuffer: '',
      startedAt: now,
      updatedAt: now
    };

    await this.deps.stateStore.saveSession(session);
    const executedTools: ToolResult[] = [];
    let rdtSummary: TurnResult['rdt'] | undefined;

    try {
      yield* this.transition(session, 'PREPARE_CONTEXT');
      yield* this.transition(session, 'PLAN_PROVIDER');

      const providerEvent: EngineEvent = { type: 'provider_selected', route: plan.primary };
      await this.emit(session.sessionId, providerEvent);
      yield providerEvent;

      yield* this.transition(session, 'MODEL_STREAMING');

      while (!['FINALIZE', 'FAILED_TERMINAL'].includes(session.state)) {
        switch (session.state) {
          case 'MODEL_STREAMING': {
            if (session.iteration >= this.deps.config.runtime.maxTurns) {
              throw this.error('budget_exhausted', 'Max model iterations exceeded', {
                maxTurns: this.deps.config.runtime.maxTurns
              });
            }

            session.iteration += 1;
            session.outputBuffer = '';
            for await (const delta of this.deps.executeModel(input, session, async (metaEvent) => {
              if (metaEvent.type === 'provider_selected') {
                session.activeProvider = metaEvent.route;
              }
              if (metaEvent.type === 'fallback_activated') {
                session.fallbackDepth += 1;
                session.activeProvider = metaEvent.route;
              }
              await this.emit(session.sessionId, metaEvent);
              // replay event to stream from engine
              (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents ??= [];
              (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents?.push(metaEvent);
            })) {
              const queued = (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents ?? [];
              while (queued.length > 0) {
                const queuedEvent = queued.shift();
                if (queuedEvent) {
                  yield queuedEvent;
                }
              }

              session.outputBuffer += delta;
              const deltaEvent: EngineEvent = { type: 'model_delta', text: delta };
              await this.emit(session.sessionId, deltaEvent);
              yield deltaEvent;
            }

            session.pendingTools = parseToolCalls(session.outputBuffer).slice(
              0,
              this.deps.config.runtime.maxToolCallsPerTurn
            );
            yield* this.transition(session, nextStateAfterModel(session.pendingTools.length > 0));
            break;
          }

          case 'TOOL_CALLS_PENDING': {
            yield* this.transition(session, session.pendingTools.length > 0 ? 'TOOL_EXECUTING' : 'MODEL_STREAMING');
            break;
          }

          case 'TOOL_EXECUTING': {
            const controller = new AbortController();
            const contextSnapshot = this.deps.contextManager
              ? await this.deps.contextManager.getSnapshot(session.sessionId, session.activeProvider.model)
              : null;
            const toolCtx = {
              sessionId: session.sessionId,
              turnId,
              signal: controller.signal,
              role: 'system' as const,
              conversationState: {
                tags: session.messages.slice(-2),
                snapshot: contextSnapshot
                  ? {
                      recentTurns: contextSnapshot.turns.slice(-5).map((turn) => `${turn.speaker}:${turn.content}`),
                      facts: contextSnapshot.memory.slice(0, 5).map((fact) => fact.fact)
                    }
                  : undefined
              },
              approvedTools: session.pendingTools.map((tool) => tool.name)
            };

            let results: ToolResult[] = [];
            if (this.deps.toolExecutor.executeBatchStream) {
              const stream = this.deps.toolExecutor.executeBatchStream(session.pendingTools, toolCtx);
              while (true) {
                const next = await stream.next();
                if (next.done) {
                  results = next.value;
                  break;
                }

                const toolEvent = next.value;
                if (toolEvent.type === 'tool_started') {
                  const startedEvent: EngineEvent = { type: 'tool_started', call: toolEvent.call };
                  await this.emit(session.sessionId, startedEvent);
                  yield startedEvent;
                } else if (toolEvent.type === 'tool_progress') {
                  const progressEvent: EngineEvent = { type: 'tool_progress', event: toolEvent.event };
                  await this.emit(session.sessionId, progressEvent);
                  yield progressEvent;
                } else if (toolEvent.type === 'tool_completed') {
                  const completedEvent: EngineEvent = { type: 'tool_completed', result: toolEvent.result };
                  await this.emit(session.sessionId, completedEvent);
                  yield completedEvent;
                }
              }
            } else {
              for (const call of session.pendingTools) {
                const startedEvent: EngineEvent = { type: 'tool_started', call };
                await this.emit(session.sessionId, startedEvent);
                yield startedEvent;
              }
              results = await this.deps.toolExecutor.executeBatch(session.pendingTools, toolCtx);
              for (const result of results) {
                const completedEvent: EngineEvent = { type: 'tool_completed', result };
                await this.emit(session.sessionId, completedEvent);
                yield completedEvent;
              }
            }

            for (const result of results) {
              executedTools.push(result);
              session.messages.push(JSON.stringify(result));
            }

            if (this.deps.learningManager) {
              for (let index = 0; index < results.length; index += 1) {
                const call = session.pendingTools[index];
                const result = results[index];
                if (!call || !result) {
                  continue;
                }
                await this.deps.learningManager.observeToolExecution({
                  sessionId: session.sessionId,
                  turnId,
                  call,
                  result,
                  contextTags: [session.activeProvider.provider, session.activeProvider.model]
                });
              }
            }

            const batchDoneEvent: EngineEvent = { type: 'tool_batch_completed', results };
            await this.emit(session.sessionId, batchDoneEvent);
            yield batchDoneEvent;

            if (this.deps.learningManager) {
              const learningCycle = await this.deps.learningManager.runCycle('engine');
              const learningEvent: EngineEvent = {
                type: 'learning_cycle',
                proposals: learningCycle.proposals.length,
                applied: learningCycle.applied.length
              };
              await this.emit(session.sessionId, learningEvent);
              yield learningEvent;
              for (const proposal of learningCycle.proposals.filter((proposal) => learningCycle.applied.includes(proposal.id))) {
                const appliedEvent: EngineEvent = {
                  type: 'learning_applied',
                  proposalId: proposal.id,
                  kind: proposal.kind
                };
                await this.emit(session.sessionId, appliedEvent);
                yield appliedEvent;
              }
            }

            session.pendingTools = [];
            yield* this.transition(session, 'MODEL_STREAMING');
            break;
          }

          case 'RDT_OPTIONAL': {
            if (this.deps.config.rdt.enabled && this.deps.runRdt) {
              const rdtResult = await this.deps.runRdt(
                {
                  prompt: input.userMessage,
                  context: session.messages.slice(-8),
                  tokenBudget: {
                    maxInputChars: 6_000,
                    maxOutputChars: 8_000
                  },
                  metadata: {
                    sessionId: input.sessionId,
                    turnId,
                    provider: session.activeProvider.provider,
                    model: session.activeProvider.model
                  }
                },
                session,
                async (rdtProgress) => {
                  const progressEvent: EngineEvent = { type: 'rdt_progress', event: rdtProgress };
                  await this.emit(session.sessionId, progressEvent);
                  (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents ??= [];
                  (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents?.push(progressEvent);
                }
              );

              const queued = (session as QuerySessionState & { __queuedEvents?: EngineEvent[] }).__queuedEvents ?? [];
              while (queued.length > 0) {
                const queuedEvent = queued.shift();
                if (queuedEvent) {
                  yield queuedEvent;
                }
              }

              session.outputBuffer = rdtResult.finalText || session.outputBuffer;
              rdtSummary = {
                enabled: true,
                loopsUsed: rdtResult.loopsUsed,
                haltedEarly: rdtResult.haltedEarly,
                finalConfidence: rdtResult.finalConfidence,
                quality: rdtResult.quality
              };

              const observabilityEvent: EngineEvent = {
                type: 'rdt_observability',
                metrics: {
                  loopsUsed: rdtResult.loopsUsed,
                  haltedEarly: rdtResult.haltedEarly,
                  finalConfidence: rdtResult.finalConfidence,
                  avgAggregateQuality: rdtResult.quality.avgAggregate
                }
              };
              await this.emit(session.sessionId, observabilityEvent);
              yield observabilityEvent;
            }
            yield* this.transition(session, 'FINALIZE');
            break;
          }

          default:
            throw this.error('fatal_runtime_error', `Unexpected state in loop: ${session.state}`);
        }
      }

      yield* this.transition(session, 'PERSIST');
      yield* this.transition(session, 'IDLE');

      const result: TurnResult = {
        sessionId: input.sessionId,
        turnId,
        finalText: session.outputBuffer,
        tools: executedTools,
        state: 'IDLE',
        usage: {
          inputChars: input.userMessage.length,
          outputChars: session.outputBuffer.length
        },
        rdt: rdtSummary
      };
      if (this.deps.contextManager) {
        await this.deps.contextManager.postTurnUpdate({
          sessionId: input.sessionId,
          turnId,
          inputMessage: input.userMessage,
          assistantMessage: session.outputBuffer,
          toolMessages: executedTools.map((tool) => JSON.stringify(tool)),
          providerRoute: session.activeProvider,
          result,
          startedAt: now,
          completedAt: Date.now()
        });
      }

      const doneEvent: EngineEvent = { type: 'turn_completed', result };
      await this.emit(session.sessionId, doneEvent);
      yield doneEvent;
      return result;
    } catch (unknownError) {
      const err = this.normalizeError(unknownError);
      const failEvent: EngineEvent = { type: 'turn_failed', error: err };
      session.lastError = err;
      assertTransition(session.state, 'FAILED_TERMINAL');
      const from = session.state;
      session.state = 'FAILED_TERMINAL';
      await this.deps.stateStore.saveSession(session);
      const failStateEvent: EngineEvent = { type: 'state_changed', from, to: 'FAILED_TERMINAL' };
      await this.emit(session.sessionId, failStateEvent);
      yield failStateEvent;
      await this.emit(session.sessionId, failEvent);
      yield failEvent;

      const result: TurnResult = {
        sessionId: input.sessionId,
        turnId,
        finalText: session.outputBuffer,
        tools: executedTools,
        state: 'FAILED_TERMINAL',
        usage: {
          inputChars: input.userMessage.length,
          outputChars: session.outputBuffer.length
        }
      };
      return result;
    }
  }

  async getState(sessionId: string): Promise<QuerySessionState | null> {
    return this.deps.stateStore.getSession(sessionId);
  }

  async abort(sessionId: string): Promise<void> {
    await this.deps.stateStore.abortSession(sessionId);
  }

  async searchHistory(query: import('../types/context.types.js').SearchQuery) {
    if (!this.deps.contextManager) {
      return [];
    }
    return this.deps.contextManager.search(query);
  }

  async listLearningProposals(status?: 'proposed' | 'approved' | 'rejected' | 'applied' | 'rolled_back') {
    if (!this.deps.learningManager) {
      return [];
    }
    return this.deps.learningManager.listProposals(status);
  }

  async applyLearningProposal(proposalId: string, approver = 'cli'): Promise<void> {
    if (!this.deps.learningManager) {
      throw new Error('Learning manager is not configured.');
    }
    await this.deps.learningManager.applyProposal(proposalId, approver);
  }

  async rollbackLearnedTool(toolName: string, targetVersionId?: number, actor = 'cli'): Promise<void> {
    if (!this.deps.learningManager) {
      throw new Error('Learning manager is not configured.');
    }
    await this.deps.learningManager.rollbackTool(toolName, targetVersionId, actor);
  }

  async getLearningMetrics() {
    if (!this.deps.learningManager) {
      return {
        observedExecutions: 0,
        proposalsCreated: 0,
        proposalsApplied: 0,
        proposalsRejected: 0,
        rollbacks: 0,
        averageSuccessRateGain: 0,
        averageLatencyGainMs: 0
      };
    }
    return this.deps.learningManager.getMetrics();
  }

  async getInterviewSession(sessionId: string) {
    if (!this.deps.interviewer) {
      return null;
    }
    const session = await this.deps.interviewer.getSession(sessionId);
    if (!session) {
      return null;
    }
    return { session, done: session.status === 'completed' };
  }

  async getInterviewPlan(sessionId: string) {
    if (!this.deps.interviewer) {
      return null;
    }
    return this.deps.interviewer.getPlan(sessionId);
  }

  async exportInterviewPlan(sessionId: string) {
    if (!this.deps.interviewer) {
      return null;
    }
    return this.deps.interviewer.exportPlan(sessionId);
  }

  private async *transition(session: QuerySessionState, to: QueryState): AsyncGenerator<EngineEvent, void, void> {
    assertTransition(session.state, to);
    const from = session.state;
    session.state = to;
    session.updatedAt = Date.now();
    await this.deps.stateStore.saveSession(session);
    const event: EngineEvent = { type: 'state_changed', from, to };
    await this.emit(session.sessionId, event);
    yield event;
  }

  private async emit(sessionId: string, event: EngineEvent): Promise<void> {
    await this.deps.stateStore.appendEvent(sessionId, event);
  }

  private error(code: ZygosError['code'], message: string, details?: Record<string, unknown>): ZygosError {
    return { code, message, details };
  }

  private normalizeError(error: unknown): ZygosError {
    if (typeof error === 'object' && error !== null && 'code' in error && 'message' in error) {
      return error as ZygosError;
    }

    return {
      code: 'fatal_runtime_error',
      message: error instanceof Error ? error.message : String(error)
    };
  }
}
