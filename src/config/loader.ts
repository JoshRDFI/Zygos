import { readFile } from 'node:fs/promises';
import { extname } from 'node:path';
import YAML from 'yaml';
import { z } from 'zod';
import { configSchema } from './schema.js';
import type { ZygosConfig } from '../types/config.types.js';

const defaultConfig: ZygosConfig = {
  runtime: {
    maxTurns: 20,
    maxToolCallsPerTurn: 8,
    enableStreamingTools: false
  },
  providers: {
    primary: {
      provider: 'ollama',
      model: 'llama3.1:8b',
      weight: 1
    },
    fallbacks: [
      {
        provider: 'openai',
        model: 'gpt-4o-mini',
        weight: 1
      },
      {
        provider: 'anthropic',
        model: 'claude-3-5-haiku-latest',
        weight: 1
      }
    ],
    retry: {
      maxAttempts: 3,
      baseDelayMs: 400,
      maxDelayMs: 5_000,
      jitterRatio: 0.2
    },
    circuitBreaker: {
      failureThreshold: 3,
      resetTimeoutMs: 30_000,
      halfOpenMaxRequests: 1
    },
    rateLimit: {
      maxRequestsPerMinute: 120,
      burst: 20
    },
    observability: {
      debug: false
    },
    gracefulDegradationMessage: 'All model providers are currently unavailable. Please retry in a moment.',
    credentials: {
      openai: {
        enabled: true,
        apiKey: '${OPENAI_API_KEY}',
        timeoutMs: 45_000,
        models: ['gpt'],
        headers: {},
        weight: 1,
        requestSizeLimitBytes: 1024 * 1024,
        requireApiKey: true
      },
      anthropic: {
        enabled: true,
        apiKey: '${ANTHROPIC_API_KEY}',
        timeoutMs: 45_000,
        models: ['claude'],
        headers: {},
        weight: 1,
        requestSizeLimitBytes: 1024 * 1024,
        requireApiKey: true
      },
      ollama: {
        enabled: true,
        baseUrl: 'http://127.0.0.1:11434',
        timeoutMs: 45_000,
        models: ['llama', 'qwen', 'mistral'],
        headers: {},
        weight: 1,
        requestSizeLimitBytes: 1024 * 1024,
        requireApiKey: false
      },
      vllm: {
        enabled: false,
        baseUrl: 'http://127.0.0.1:8000/v1',
        timeoutMs: 45_000,
        models: ['llama', 'mistral', 'qwen'],
        headers: {},
        weight: 1,
        requestSizeLimitBytes: 1024 * 1024,
        requireApiKey: false
      },
      custom: {
        enabled: true,
        timeoutMs: 30_000,
        models: [],
        headers: {},
        weight: 1,
        requestSizeLimitBytes: 256 * 1024,
        requireApiKey: false
      }
    }
  },
  rdt: {
    enabled: false,
    profile: 'balanced',
    prelude: {
      enabled: true,
      temperature: 0.1,
      maxTokens: 512,
      systemInstruction: 'Initialize context and decompose the task into structured sub-problems.'
    },
    recurrent: {
      enabled: true,
      temperature: 0.2,
      maxTokens: 700,
      minLoopIters: 1,
      maxLoopIters: 4,
      allowBacktracking: true,
      allowParallelPaths: true,
      systemInstruction: 'Iteratively refine reasoning with consistency checks and revisions.'
    },
    coda: {
      enabled: true,
      temperature: 0.1,
      maxTokens: 900,
      systemInstruction: 'Synthesize a concise, correct final answer.'
    },
    loop: {
      maxLoopIters: 4,
      minLoopIters: 1,
      maxRevisionDepth: 2
    },
    confidence: {
      thresholds: {
        earlyExit: 0.84,
        revise: 0.55,
        floor: 0.25
      },
      adaptive: true,
      adaptUpDelta: 0.03,
      adaptDownDelta: 0.04,
      smoothingFactor: 0.55
    },
    attention: {
      defaultMode: 'auto',
      switchByTask: true,
      modeSwitchComplexityThreshold: 0.55,
      moe: {
        enabled: true,
        routedExperts: ['math', 'coding', 'research', 'planning'],
        sharedExperts: ['synthesis', 'verification'],
        topK: 2,
        maxParallelExperts: 3,
        loadBalanceWindow: 10
      }
    },
    quality: {
      enableTraceLogging: true,
      preserveReasoningChain: true,
      computeAdaptive: true,
      enableMultiHop: true
    }
  },
  learning: {
    enabled: true,
    approvalMode: 'auto',
    autoApplyLowRisk: true,
    maxProposalsPerCycle: 3,
    minObservationsForProposal: 8,
    observeWindowSize: 200,
    maxModificationsPerHour: 20,
    maxToolCreationsPerDay: 20,
    abTestSampleSize: 6,
    maxLatencyRegressionRatio: 0.2,
    minSuccessRateGain: 0.03,
    maxResourceCostPerTestMs: 8_000
  },
  interview: {
    enabled: true,
    requireForComplexBuilds: true,
    complexityThreshold: 3.25,
    maxQuestions: 12,
    allowBypassForSimpleRequests: true,
    allowOverrideByFlag: true,
    template: 'auto'
  }
};

function migrateLegacyConfig(parsed: Record<string, unknown>): Record<string, unknown> {
  const migrated = { ...parsed };
  if (!migrated.providers && migrated.provider && typeof migrated.provider === 'object') {
    migrated.providers = migrated.provider;
    delete migrated.provider;
  }
  return migrated;
}

function resolveEnvPlaceholders(value: unknown, keyPath = ''): unknown {
  if (typeof value === 'string') {
    const match = value.match(/^\$\{([A-Z0-9_]+)\}$/i);
    if (!match) {
      return value;
    }

    const envName = match[1];
    const envValue = process.env[envName];
    if (!envValue) {
      return undefined;
    }
    return envValue;
  }

  if (Array.isArray(value)) {
    return value.map((item, index) => resolveEnvPlaceholders(item, `${keyPath}[${index}]`));
  }

  if (value && typeof value === 'object') {
    const objectValue = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(objectValue).map(([key, nested]) => {
        const nextPath = keyPath ? `${keyPath}.${key}` : key;
        return [key, resolveEnvPlaceholders(nested, nextPath)];
      })
    );
  }

  return value;
}

function validateCredentialRequirements(config: ZygosConfig): void {
  const routes = [config.providers.primary, ...config.providers.fallbacks];
  for (const route of routes) {
    const credential = config.providers.credentials[route.provider as keyof typeof config.providers.credentials];
    if (!credential || credential.enabled === false) {
      continue;
    }

    const requireApiKey = credential.requireApiKey ?? ['openai', 'anthropic'].includes(route.provider);
    if (requireApiKey && !credential.apiKey) {
      // eslint-disable-next-line no-console
      console.warn(
        `[config] Missing apiKey for route ${route.provider}:${route.model}. Route will be skipped at runtime unless env var is set.`
      );
    }
  }
}

export async function loadConfig(configPath?: string): Promise<ZygosConfig> {
  if (!configPath) {
    return configSchema.parse(resolveEnvPlaceholders(defaultConfig)) as ZygosConfig;
  }

  const raw = await readFile(configPath, 'utf8');
  const extension = extname(configPath).toLowerCase();

  let parsedUnknown: unknown;
  if (extension === '.yaml' || extension === '.yml') {
    parsedUnknown = YAML.parse(raw);
  } else {
    parsedUnknown = JSON.parse(raw);
  }

  const migrated = migrateLegacyConfig((parsedUnknown ?? {}) as Record<string, unknown>);
  const providers = (migrated.providers ?? {}) as Record<string, unknown>;
  const credentials = (providers.credentials ?? {}) as Record<string, unknown>;

  try {
    const mergedConfig = {
      ...defaultConfig,
      ...migrated,
      providers: {
        ...defaultConfig.providers,
        ...providers,
        retry: {
          ...defaultConfig.providers.retry,
          ...((providers.retry as Record<string, unknown>) ?? {})
        },
        circuitBreaker: {
          ...defaultConfig.providers.circuitBreaker,
          ...((providers.circuitBreaker as Record<string, unknown>) ?? {})
        },
        rateLimit: {
          ...defaultConfig.providers.rateLimit,
          ...((providers.rateLimit as Record<string, unknown>) ?? {})
        },
        observability: {
          ...defaultConfig.providers.observability,
          ...((providers.observability as Record<string, unknown>) ?? {})
        },
        credentials: {
          ...defaultConfig.providers.credentials,
          ...credentials
        }
      }
    };

    const withResolvedEnv = resolveEnvPlaceholders(mergedConfig);
    const validated = configSchema.parse(withResolvedEnv) as ZygosConfig;
    validateCredentialRequirements(validated);
    return validated;
  } catch (error) {
    if (error instanceof z.ZodError) {
      const details = error.issues.map((issue) => `${issue.path.join('.') || 'root'}: ${issue.message}`).join('; ');
      throw new Error(`Configuration validation failed: ${details}`);
    }
    throw error;
  }
}
