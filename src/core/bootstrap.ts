import { z } from 'zod';
import { loadConfig } from '../config/loader.js';
import { QueryEngineImpl } from './engine.js';
import { InMemoryStateStore } from './state.js';
import { ToolExecutor } from '../tools/executor.js';
import { BasicToolRegistry } from '../tools/registry.js';
import { BaseProvider } from '../providers/base.provider.js';
import { OpenAIProvider } from '../providers/openai.provider.js';
import { AnthropicProvider } from '../providers/anthropic.provider.js';
import { OllamaProvider } from '../providers/ollama.provider.js';
import { VllmProvider } from '../providers/vllm.provider.js';
import { ProviderRouterImpl } from '../providers/router.js';
import { StructuredLogger } from '../providers/observability.js';
import { ContextManager } from '../context/manager.js';
import { SQLiteContextStorage } from '../context/storage.js';
import { RDTRuntime } from '../reasoning/rdt-runtime.js';
import { LearningManager } from '../learning/manager.js';
import { Interviewer } from '../interviewer/interviewer.js';
import { RDT_PROFILES } from '../types/rdt.types.js';
import type { EngineEvent, QueryEngine, QueryEngineDeps, QuerySessionState, UserTurnInput } from '../types/core.types.js';
import type { ModelRequest, ModelResponse, ProviderCapabilities, ProviderConfig, ProviderStreamEvent } from '../types/provider.types.js';
import type { RDTConfig, RDTProgressEvent, ReasoningDepthProfile } from '../types/rdt.types.js';

class CustomDemoProvider extends BaseProvider {
  readonly key = 'custom' as const;

  readonly capabilities: ProviderCapabilities = {
    streaming: true,
    toolCalling: true,
    maxContextTokens: 32_000,
    protocols: ['openai_chat', 'anthropic_messages']
  };

  async complete(request: ModelRequest): Promise<ModelResponse> {
    const text = this.renderResponse(this.validateAndSanitizeRequest(request));
    return { text };
  }

  async *stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void> {
    const text = this.renderResponse(this.validateAndSanitizeRequest(request));
    const chunks = text.match(/.{1,24}/g) ?? [text];
    for (const chunk of chunks) {
      yield { type: 'delta', text: chunk };
    }
    yield { type: 'done', response: { text } };
  }

  private renderResponse(request: ModelRequest): string {
    const latestUser = [...request.messages].reverse().find((message) => message.role === 'user')?.content ?? '';
    const toolSummary = request.messages
      .filter((m) => m.role === 'tool')
      .map((m) => m.content)
      .join('\n');

    if (toolSummary.length > 0) {
      return `Tool execution complete.\n${toolSummary}`;
    }

    if (latestUser.startsWith('/time ')) {
      return `[[tool:get_time {"zone":"${latestUser.replace('/time ', '').trim()}"}]]`;
    }

    return `Assistant response (${request.model}): ${latestUser}`;
  }
}

function sanitizeContent(content: string): string {
  return content.replaceAll('\u0000', '').replace(/\r\n/g, '\n').trim();
}

function toProviderMessages(input: UserTurnInput, session: QuerySessionState): Array<{ role: 'user' | 'assistant' | 'tool'; content: string }> {
  const messages: Array<{ role: 'user' | 'assistant' | 'tool'; content: string }> = [];
  for (let i = 0; i < session.messages.length; i += 1) {
    const isLast = i === session.messages.length - 1;
    messages.push({
      role: isLast ? 'user' : 'assistant',
      content: sanitizeContent(session.messages[i])
    });
  }

  if (messages.length === 0) {
    messages.push({ role: 'user', content: sanitizeContent(input.userMessage) });
  }

  return messages;
}

function buildProviders(configProviders: Record<string, ProviderConfig>): BaseProvider[] {
  const candidates: BaseProvider[] = [
    new OpenAIProvider((configProviders.openai ?? {}) as ProviderConfig),
    new AnthropicProvider((configProviders.anthropic ?? {}) as ProviderConfig),
    new OllamaProvider((configProviders.ollama ?? {}) as ProviderConfig),
    new VllmProvider((configProviders.vllm ?? {}) as ProviderConfig),
    new CustomDemoProvider((configProviders.custom ?? {}) as ProviderConfig)
  ];

  return candidates.filter((provider) => provider.config.enabled !== false);
}

function mergeRdtProfile(config: RDTConfig, profile: ReasoningDepthProfile): RDTConfig {
  const profilePatch = RDT_PROFILES[profile] ?? {};
  return {
    ...config,
    profile,
    prelude: { ...config.prelude, ...(profilePatch.prelude ?? {}) },
    recurrent: { ...config.recurrent, ...(profilePatch.recurrent ?? {}) },
    coda: { ...config.coda, ...(profilePatch.coda ?? {}) },
    loop: { ...config.loop, ...(profilePatch.loop ?? {}) },
    confidence: {
      ...config.confidence,
      ...(profilePatch.confidence ?? {}),
      thresholds: {
        ...config.confidence.thresholds,
        ...(profilePatch.confidence?.thresholds ?? {})
      }
    },
    attention: {
      ...config.attention,
      ...(profilePatch.attention ?? {}),
      moe: {
        ...config.attention.moe,
        ...(profilePatch.attention?.moe ?? {})
      }
    },
    quality: { ...config.quality, ...(profilePatch.quality ?? {}) }
  };
}

/** Creates a fully wired query engine with hardened provider routing and validation. */
export async function createEngine(
  configPath?: string,
  routeOverride?: { provider?: string; model?: string; rdtEnabled?: boolean; rdtProfile?: ReasoningDepthProfile }
): Promise<QueryEngine> {
  const config = await loadConfig(configPath);
  if (routeOverride?.rdtProfile) {
    config.rdt = mergeRdtProfile(config.rdt, routeOverride.rdtProfile);
  }
  if (typeof routeOverride?.rdtEnabled === 'boolean') {
    config.rdt.enabled = routeOverride.rdtEnabled;
  }

  const logger = new StructuredLogger('core.bootstrap', config.providers.observability.debug);

  if (routeOverride?.provider) {
    config.providers.primary.provider = routeOverride.provider;
    config.providers.fallbacks = [];
    const credentials = config.providers.credentials as Record<string, { enabled?: boolean }>;
    if (credentials[routeOverride.provider]) {
      credentials[routeOverride.provider].enabled = true;
    }
  }
  if (routeOverride?.model) {
    config.providers.primary.model = routeOverride.model;
    if (routeOverride?.provider) {
      config.providers.fallbacks = [];
    }
  }

  const stateStore = new InMemoryStateStore();
  const contextDbPath = process.env.ZYGOS_CONTEXT_DB ?? '.zygos/context.db';
  const contextManager = new ContextManager(new SQLiteContextStorage({ dbPath: contextDbPath }), {
    defaultModelContextTokens: 32_000
  });

  const registry = new BasicToolRegistry();
  registry.register({
    meta: {
      name: 'get_time',
      description: 'Return current ISO timestamp for a target zone identifier.',
      version: '1.0.0',
      timeoutMs: 1_000,
      concurrency: 'serial_only',
      destructive: false,
      permission: 'allow',
      aliases: []
    },
    inputSchema: z.object({ zone: z.string().min(1) }),
    outputSchema: z.object({ zone: z.string(), nowIso: z.string() }),
    async execute(input: { zone: string }) {
      return { zone: input.zone, nowIso: new Date().toISOString() };
    }
  });

  const toolExecutor = new ToolExecutor(registry);
  const learningDbPath = process.env.ZYGOS_LEARNING_DB ?? '.zygos/learning.db';
  const learningManager = new LearningManager({
    config: config.learning,
    dbPath: learningDbPath,
    runtime: {
      listTools: () => registry.list(),
      getTool: (name) => registry.getByName(name),
      registerTool: (definition) => registry.register(definition),
      updateTool: (name, definition) => {
        if (!registry.update) {
          throw new Error('Tool registry does not support update operations.');
        }
        registry.update(name, definition);
      },
      removeTool: (name) => registry.remove?.(name),
      executeForLearning: async (call) => {
        const result = await toolExecutor.execute(call, {
          sessionId: 'learning_session',
          turnId: `learning_turn_${Date.now()}`,
          signal: new AbortController().signal,
          role: 'system'
        });
        return result;
      }
    }
  });
  await learningManager.init();

  const providers = buildProviders(config.providers.credentials as Record<string, ProviderConfig>);
  if (providers.length === 0) {
    throw new Error('No enabled providers are configured.');
  }

  const providerRouter = new ProviderRouterImpl(providers, {
    retry: config.providers.retry,
    circuitBreaker: config.providers.circuitBreaker,
    rateLimit: config.providers.rateLimit,
    observability: config.providers.observability,
    gracefulDegradationMessage: config.providers.gracefulDegradationMessage
  });

  const interviewer = new Interviewer({
    dbPath: process.env.ZYGOS_INTERVIEW_DB ?? contextDbPath,
    config: config.interview,
    askProvider: async (prompt: string) => {
      const interviewInput: UserTurnInput = {
        sessionId: `interview_provider_${Date.now()}`,
        userMessage: prompt,
        mode: 'interview'
      };
      const interviewPlan = await providerRouter.plan({
        userInput: interviewInput,
        routes: [
          {
            provider: config.providers.primary.provider as QuerySessionState['activeProvider']['provider'],
            model: config.providers.primary.model,
            reason: 'interviewer_question'
          },
          ...config.providers.fallbacks.map((fallback, index) => ({
            provider: fallback.provider as QuerySessionState['activeProvider']['provider'],
            model: fallback.model,
            reason: `interviewer_fallback_${index + 1}`
          }))
        ]
      });

      let text = '';
      for await (const delta of providerRouter.streamWithFallback(
        interviewInput,
        [{ role: 'user', content: prompt }],
        interviewPlan,
        async () => {
          // no-op for interviewer question polish
        }
      )) {
        text += delta;
      }
      return text || prompt;
    }
  });
  await interviewer.init();

  logger.log('info', 'Engine bootstrapped with providers.', {
    providers: providers.map((provider) => provider.key),
    primary: config.providers.primary,
    fallbackCount: config.providers.fallbacks.length,
    rdtEnabled: config.rdt.enabled,
    rdtProfile: config.rdt.profile
  });

  const deps: QueryEngineDeps = {
    config,
    stateStore,
    toolExecutor,
    contextManager,
    learningManager,
    interviewer,
    pickProviderPlan: async (input) => {
      const routes = [
        {
          provider: config.providers.primary.provider as QuerySessionState['activeProvider']['provider'],
          model: config.providers.primary.model,
          reason: 'primary_config'
        },
        ...config.providers.fallbacks.map((fallback, index) => ({
          provider: fallback.provider as QuerySessionState['activeProvider']['provider'],
          model: fallback.model,
          reason: `fallback_${index + 1}`
        }))
      ];

      return providerRouter.plan({
        userInput: input,
        routes
      });
    },
    executeModel: async function* (
      input: UserTurnInput,
      session: QuerySessionState,
      emitMeta: (event: Extract<EngineEvent, { type: 'provider_selected' | 'retry_scheduled' | 'fallback_activated' }>) => Promise<void>
    ): AsyncGenerator<string, string, void> {
      const plan = session.providerPlan;
      if (!plan) {
        throw new Error('Provider plan is missing for model execution.');
      }

      const messages = toProviderMessages(input, session);
      return yield* providerRouter.streamWithFallback(input, messages, plan, emitMeta);
    },
    runRdt: async (input, session, emitProgress) => {
      if (!config.rdt.enabled) {
        return {
          finalText: session.outputBuffer,
          loopsUsed: 0,
          haltedEarly: true,
          finalConfidence: 0,
          quality: {
            avgCoherence: 0,
            avgCompleteness: 0,
            avgConsistency: 0,
            avgAggregate: 0
          }
        };
      }

      const runtime = new RDTRuntime({
        config: config.rdt,
        emit: async (event: RDTProgressEvent) => {
          await emitProgress(event);
        },
        invoke: async function* (request) {
          const plan = session.providerPlan;
          if (!plan) {
            throw new Error('Provider plan is missing for RDT invocation.');
          }

          const pseudoInput: UserTurnInput = {
            sessionId: session.sessionId,
            userMessage: request.prompt,
            mode: 'standard'
          };

          const messages: Array<{ role: 'user' | 'assistant' | 'tool'; content: string }> = [{ role: 'user', content: request.prompt }];
          let finalText = '';
          for await (const delta of providerRouter.streamWithFallback(pseudoInput, messages, plan, async (metaEvent) => {
            await emitProgress({
              type: 'rdt_trace',
              message: 'provider_meta',
              data: metaEvent as unknown as Record<string, unknown>
            });
          })) {
            finalText += delta;
            yield delta;
          }

          return finalText;
        }
      });

      return runtime.run(input);
    }
  };

  return new QueryEngineImpl(deps);
}
