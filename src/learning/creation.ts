import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import type { LearningProposal, LearningRuntimeDeps, ToolCreationProposal, ToolCreationSpec, ToolExecutionObservation } from '../types/learning.types.js';
import type { ToolDefinition } from '../types/tool.types.js';

interface CreationOptions {
  minPatternFrequency: number;
  maxToolCreationsPerDay: number;
}

const SAFE_TEMPLATE_ALLOWLIST = new Set(['json_transform', 'text_template', 'math_expression']);

export class ToolCreationEngine {
  constructor(
    private readonly runtime: LearningRuntimeDeps,
    private readonly options: CreationOptions
  ) {}

  detectOpportunities(observations: ToolExecutionObservation[]): ToolCreationSpec[] {
    const failureByName = new Map<string, { count: number; keys: Map<string, number> }>();
    for (const obs of observations) {
      const unknownTool = !this.runtime.getTool(obs.toolCall.name);
      const failed = !obs.result.ok;
      if (!unknownTool && !failed) {
        continue;
      }

      const bucket = failureByName.get(obs.toolCall.name) ?? { count: 0, keys: new Map<string, number>() };
      bucket.count += 1;
      for (const key of Object.keys(obs.toolCall.input ?? {})) {
        bucket.keys.set(key, (bucket.keys.get(key) ?? 0) + 1);
      }
      failureByName.set(obs.toolCall.name, bucket);
    }

    const specs: ToolCreationSpec[] = [];
    for (const [name, bucket] of failureByName) {
      if (bucket.count < this.options.minPatternFrequency) {
        continue;
      }
      const requiredKeys = [...bucket.keys.entries()]
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
        .map(([key]) => key);

      specs.push({
        name: sanitizeToolName(name),
        description: `Auto-generated tool for recurring pattern: ${name}`,
        template: pickTemplate(requiredKeys),
        requiredKeys,
        parameterHints: Object.fromEntries(requiredKeys.map((key) => [key, 'string']))
      });
    }

    return specs.slice(0, this.options.maxToolCreationsPerDay);
  }

  buildProposal(spec: ToolCreationSpec): LearningProposal {
    const definition = this.generateTool(spec);
    const validation = this.validateGeneratedTool(definition, spec);

    const payload: ToolCreationProposal = {
      type: 'creation',
      spec,
      generatedDefinition: definition,
      validationReport: validation,
      explanation: `Generated ${spec.template} tool from recurring runtime pattern.`
    };

    return {
      id: randomUUID(),
      kind: 'creation',
      status: 'proposed',
      source: 'heuristic',
      requestedBy: 'learning_manager',
      risk: validation.passed ? 'low' : 'high',
      payload,
      createdAt: Date.now(),
      updatedAt: Date.now()
    };
  }

  applyProposal(proposal: ToolCreationProposal): void {
    if (!proposal.validationReport.passed) {
      throw new Error(`Tool creation blocked by safety validation: ${proposal.validationReport.blockedReasons.join('; ')}`);
    }

    const existing = this.runtime.getTool(proposal.spec.name);
    if (existing) {
      this.runtime.updateTool(existing.meta.name, proposal.generatedDefinition);
      return;
    }
    this.runtime.registerTool(proposal.generatedDefinition);
  }

  validateGeneratedTool(definition: ToolDefinition, spec: ToolCreationSpec): {
    passed: boolean;
    warnings: string[];
    blockedReasons: string[];
  } {
    const warnings: string[] = [];
    const blockedReasons: string[] = [];

    if (!SAFE_TEMPLATE_ALLOWLIST.has(spec.template)) {
      blockedReasons.push(`Template '${spec.template}' is not allowlisted.`);
    }

    if (!/^[a-zA-Z0-9_.-]+$/.test(definition.meta.name)) {
      blockedReasons.push('Tool name must match safe identifier constraints.');
    }

    if (spec.requiredKeys.length === 0) {
      warnings.push('Tool has no required keys; behavior may be too generic.');
    }

    const serialized = JSON.stringify(definition.meta);
    if (/process\.|globalThis|Function\(|eval\(|import\(/i.test(serialized)) {
      blockedReasons.push('Generated metadata includes suspicious code-like patterns.');
    }

    return {
      passed: blockedReasons.length === 0,
      warnings,
      blockedReasons
    };
  }

  private generateTool(spec: ToolCreationSpec): ToolDefinition {
    const dynamicInputSchema = z.object(
      Object.fromEntries(spec.requiredKeys.map((key) => [key, z.union([z.string(), z.number(), z.boolean(), z.null()]).optional()]))
    ).passthrough();

    const outputSchema = z.object({
      template: z.string(),
      rendered: z.string(),
      meta: z.record(z.unknown())
    });

    return {
      meta: {
        name: spec.name,
        description: spec.description,
        version: '1.0.0',
        timeoutMs: 1_000,
        concurrency: 'safe_parallel',
        destructive: false,
        permission: 'allow',
        aliases: [],
        parallelHint: 'safe',
        retry: { attempts: 1, backoffMs: 100 },
        resultFormat: 'json',
        maxResultBytes: 64 * 1024
      },
      inputSchema: dynamicInputSchema,
      outputSchema,
      async execute(input) {
        return {
          template: spec.template,
          rendered: renderFromTemplate(spec.template, input as Record<string, unknown>, spec.requiredKeys),
          meta: {
            generated: true,
            parameterHints: spec.parameterHints
          }
        };
      }
    };
  }
}

function pickTemplate(requiredKeys: string[]): ToolCreationSpec['template'] {
  if (requiredKeys.some((key) => /(sum|count|value|num|price|quantity)/i.test(key))) {
    return 'math_expression';
  }
  if (requiredKeys.some((key) => /(json|path|field|key)/i.test(key))) {
    return 'json_transform';
  }
  return 'text_template';
}

function sanitizeToolName(raw: string): string {
  const safe = raw.toLowerCase().replace(/[^a-z0-9_.-]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '');
  return safe.length > 2 ? safe : `generated_${safe || 'tool'}`;
}

function renderFromTemplate(template: ToolCreationSpec['template'], input: Record<string, unknown>, keys: string[]): string {
  if (template === 'math_expression') {
    const total = keys.reduce((acc, key) => acc + Number(input[key] ?? 0), 0);
    return `sum=${Number.isFinite(total) ? total : 0}`;
  }

  if (template === 'json_transform') {
    const projection = Object.fromEntries(keys.map((key) => [key, input[key] ?? null]));
    return JSON.stringify(projection);
  }

  return keys.map((key) => `${key}=${stringify(input[key])}`).join(' | ');
}

function stringify(value: unknown): string {
  if (value === undefined) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}
