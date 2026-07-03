import { z } from 'zod';

const providerKeySchema = z.enum(['openai', 'anthropic', 'ollama', 'vllm', 'custom']);
const envVarTemplateSchema = z.string().regex(/^\$\{[A-Z0-9_]+\}$/i, 'Expected ${ENV_VAR_NAME} placeholder.');

const attentionModeSchema = z.enum(['mla', 'gqa', 'auto']);
const reasoningDepthProfileSchema = z.enum(['shallow', 'balanced', 'deep']);
const learningApprovalModeSchema = z.enum(['auto', 'manual', 'optional_human']);
const interviewTemplateSchema = z.enum(['auto', 'web_app', 'data_pipeline', 'api_service', 'tool_utility', 'general']);

export const providerRouteSchema = z.object({
  provider: providerKeySchema,
  model: z.string().trim().min(1, 'Model is required.'),
  weight: z.number().min(0).max(1).default(1)
});

const endpointSchema = z
  .string()
  .trim()
  .url('baseUrl must be a valid URL.')
  .refine((url) => {
    try {
      const parsed = new URL(url);
      return ['https:', 'http:'].includes(parsed.protocol);
    } catch {
      return false;
    }
  }, 'baseUrl protocol must be http or https.');

export const providerCredentialSchema = z.object({
  apiKey: z.union([z.string().trim().min(1), envVarTemplateSchema]).optional(),
  baseUrl: endpointSchema.optional(),
  organization: z.string().trim().min(1).optional(),
  protocol: z.enum(['openai_chat', 'anthropic_messages']).optional(),
  timeoutMs: z.number().int().positive().max(180_000).optional(),
  enabled: z.boolean().default(true),
  models: z.array(z.string().trim().min(1)).default([]),
  headers: z.record(z.string().trim().min(1)).default({}),
  weight: z.number().min(0).max(10).default(1),
  requestSizeLimitBytes: z.number().int().positive().max(10 * 1024 * 1024).default(1024 * 1024),
  requireApiKey: z.boolean().optional()
});

const retrySchema = z
  .object({
    maxAttempts: z.number().int().positive().max(10).default(3),
    baseDelayMs: z.number().int().positive().max(30_000).default(400),
    maxDelayMs: z.number().int().positive().max(120_000).default(5_000),
    jitterRatio: z.number().min(0).max(1).default(0.2)
  })
  .superRefine((value, ctx) => {
    if (value.maxDelayMs < value.baseDelayMs) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'providers.retry.maxDelayMs must be >= providers.retry.baseDelayMs.',
        path: ['maxDelayMs']
      });
    }
  });

const circuitBreakerSchema = z.object({
  failureThreshold: z.number().int().positive().max(50).default(3),
  resetTimeoutMs: z.number().int().positive().max(300_000).default(30_000),
  halfOpenMaxRequests: z.number().int().positive().max(10).default(1)
});

const rateLimitSchema = z.object({
  maxRequestsPerMinute: z.number().int().positive().max(10_000).default(120),
  burst: z.number().int().positive().max(2_000).default(20)
});

const stageConfigSchema = z.object({
  enabled: z.boolean().default(true),
  temperature: z.number().min(0).max(2).default(0.2),
  maxTokens: z.number().int().positive().max(8192).optional(),
  systemInstruction: z.string().trim().min(1)
});

const recurrentStageConfigSchema = stageConfigSchema.extend({
  minLoopIters: z.number().int().nonnegative().default(1),
  maxLoopIters: z.number().int().positive().default(4),
  allowBacktracking: z.boolean().default(true),
  allowParallelPaths: z.boolean().default(true)
});

const rdtSchema = z
  .object({
    enabled: z.boolean().default(false),
    profile: reasoningDepthProfileSchema.default('balanced'),
    prelude: stageConfigSchema.default({
      enabled: true,
      temperature: 0.1,
      systemInstruction: 'Initialize context and decompose the task into structured sub-problems.',
      maxTokens: 512
    }),
    recurrent: recurrentStageConfigSchema.default({
      enabled: true,
      temperature: 0.2,
      minLoopIters: 1,
      maxLoopIters: 4,
      allowBacktracking: true,
      allowParallelPaths: true,
      systemInstruction: 'Iteratively refine reasoning with consistency checks and revisions.',
      maxTokens: 700
    }),
    coda: stageConfigSchema.default({
      enabled: true,
      temperature: 0.1,
      systemInstruction: 'Synthesize a concise, correct final answer.',
      maxTokens: 900
    }),
    loop: z.object({
      maxLoopIters: z.number().int().positive().default(4),
      minLoopIters: z.number().int().nonnegative().default(1),
      maxRevisionDepth: z.number().int().nonnegative().default(2)
    }),
    confidence: z.object({
      thresholds: z.object({
        earlyExit: z.number().min(0).max(1).default(0.84),
        revise: z.number().min(0).max(1).default(0.55),
        floor: z.number().min(0).max(1).default(0.25)
      }),
      adaptive: z.boolean().default(true),
      adaptUpDelta: z.number().min(0).max(1).default(0.03),
      adaptDownDelta: z.number().min(0).max(1).default(0.04),
      smoothingFactor: z.number().min(0).max(1).default(0.55)
    }),
    attention: z.object({
      defaultMode: attentionModeSchema.default('auto'),
      switchByTask: z.boolean().default(true),
      modeSwitchComplexityThreshold: z.number().min(0).max(1).default(0.55),
      moe: z.object({
        enabled: z.boolean().default(true),
        routedExperts: z.array(z.string().trim().min(1)).default(['math', 'coding', 'research', 'planning']),
        sharedExperts: z.array(z.string().trim().min(1)).default(['synthesis', 'verification']),
        topK: z.number().int().positive().max(8).default(2),
        maxParallelExperts: z.number().int().positive().max(8).default(3),
        loadBalanceWindow: z.number().int().positive().max(50).default(10)
      })
    }),
    quality: z.object({
      enableTraceLogging: z.boolean().default(true),
      preserveReasoningChain: z.boolean().default(true),
      computeAdaptive: z.boolean().default(true),
      enableMultiHop: z.boolean().default(true)
    })
  })
  .superRefine((rdt, ctx) => {
    if (rdt.recurrent.maxLoopIters < rdt.recurrent.minLoopIters) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'rdt.recurrent.maxLoopIters must be >= rdt.recurrent.minLoopIters.',
        path: ['recurrent', 'maxLoopIters']
      });
    }
    if (rdt.loop.maxLoopIters < rdt.loop.minLoopIters) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'rdt.loop.maxLoopIters must be >= rdt.loop.minLoopIters.',
        path: ['loop', 'maxLoopIters']
      });
    }
    if (rdt.confidence.thresholds.earlyExit < rdt.confidence.thresholds.revise) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: 'rdt.confidence.thresholds.earlyExit must be >= rdt.confidence.thresholds.revise.',
        path: ['confidence', 'thresholds', 'earlyExit']
      });
    }
  });

const learningSchema = z.object({
  enabled: z.boolean().default(true),
  approvalMode: learningApprovalModeSchema.default('manual'),
  autoApplyLowRisk: z.boolean().default(false),
  maxProposalsPerCycle: z.number().int().positive().max(20).default(3),
  minObservationsForProposal: z.number().int().positive().max(200).default(8),
  observeWindowSize: z.number().int().positive().max(2000).default(200),
  maxModificationsPerHour: z.number().int().positive().max(200).default(20),
  maxToolCreationsPerDay: z.number().int().positive().max(200).default(20),
  abTestSampleSize: z.number().int().positive().max(200).default(6),
  maxLatencyRegressionRatio: z.number().min(0).max(1).default(0.2),
  minSuccessRateGain: z.number().min(0).max(1).default(0.03),
  maxResourceCostPerTestMs: z.number().int().positive().max(120_000).default(8_000)
});

const interviewSchema = z.object({
  enabled: z.boolean().default(true),
  requireForComplexBuilds: z.boolean().default(true),
  complexityThreshold: z.number().min(0).max(20).default(3.25),
  maxQuestions: z.number().int().positive().max(50).default(12),
  allowBypassForSimpleRequests: z.boolean().default(true),
  allowOverrideByFlag: z.boolean().default(true),
  template: interviewTemplateSchema.default('auto')
});

export const configSchema = z.object({
  runtime: z.object({
    maxTurns: z.number().int().positive().default(20),
    maxToolCallsPerTurn: z.number().int().positive().default(8),
    enableStreamingTools: z.boolean().default(false)
  }),
  providers: z
    .object({
      primary: providerRouteSchema,
      fallbacks: z.array(providerRouteSchema).default([]),
      retry: retrySchema,
      circuitBreaker: circuitBreakerSchema,
      rateLimit: rateLimitSchema,
      observability: z.object({
        debug: z.boolean().default(false)
      }),
      gracefulDegradationMessage: z.string().trim().min(1).optional(),
      credentials: z.object({
        openai: providerCredentialSchema.optional(),
        anthropic: providerCredentialSchema.optional(),
        ollama: providerCredentialSchema.optional(),
        vllm: providerCredentialSchema.optional(),
        custom: providerCredentialSchema.optional()
      })
    })
    .superRefine((providers, ctx) => {
      const routeIds = new Set<string>();
      const allRoutes = [providers.primary, ...providers.fallbacks];
      for (const [index, route] of allRoutes.entries()) {
        const id = `${route.provider}:${route.model}`;
        if (routeIds.has(id)) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            message: `Duplicate provider route detected: ${id}.`,
            path: index === 0 ? ['primary'] : ['fallbacks', index - 1]
          });
        }
        routeIds.add(id);
      }

      if (providers.rateLimit.burst > providers.rateLimit.maxRequestsPerMinute) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: 'providers.rateLimit.burst must be <= providers.rateLimit.maxRequestsPerMinute.',
          path: ['rateLimit', 'burst']
        });
      }
    }),
  rdt: rdtSchema,
  learning: learningSchema,
  interview: interviewSchema
});
