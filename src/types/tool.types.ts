import { z } from 'zod';

export const permissionDecisionSchema = z.enum(['allow', 'deny', 'require_approval']);
export type PermissionDecision = z.infer<typeof permissionDecisionSchema>;

export const toolParallelHintSchema = z.enum(['safe', 'unsafe']).default('unsafe');
export type ToolParallelHint = z.infer<typeof toolParallelHintSchema>;

export const resultFormatSchema = z.enum(['json', 'text', 'binary']).default('json');
export type ResultFormat = z.infer<typeof resultFormatSchema>;

export const toolMetaSchema = z.object({
  name: z.string().regex(/^[a-zA-Z0-9_.-]+$/),
  description: z.string().min(1),
  version: z.string().default('1.0.0'),
  timeoutMs: z.number().int().positive().default(30_000),
  concurrency: z.enum(['safe_parallel', 'serial_only']).default('serial_only'),
  destructive: z.boolean().default(false),
  permission: z.enum(['allow', 'ask', 'deny']).default('allow'),
  aliases: z.array(z.string()).default([]),
  permissionRequirement: permissionDecisionSchema.optional(),
  parallelHint: toolParallelHintSchema.optional(),
  dependencies: z.array(z.string().regex(/^[a-zA-Z0-9_.-]+$/)).optional(),
  resultFormat: resultFormatSchema.optional(),
  maxResultBytes: z.number().int().positive().optional(),
  retry: z
    .object({
      attempts: z.number().int().min(1).max(5).default(1),
      backoffMs: z.number().int().min(0).max(30_000).default(250)
    })
    .optional(),
  fallbackTool: z.string().regex(/^[a-zA-Z0-9_.-]+$/).optional()
});

export const toolCallSchema = z.object({
  id: z.string(),
  name: z.string(),
  input: z.record(z.unknown())
});

export const normalizedToolErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  retryable: z.boolean().default(false),
  details: z.record(z.unknown()).optional()
});

export const toolResultSchema = z.object({
  toolCallId: z.string(),
  ok: z.boolean(),
  output: z.unknown().optional(),
  error: z.string().optional(),
  normalizedError: normalizedToolErrorSchema.optional(),
  durationMs: z.number().int().nonnegative(),
  synthetic: z.boolean().default(false),
  partial: z.boolean().default(false),
  bytes: z.number().int().nonnegative().optional(),
  warnings: z.array(z.string()).default([])
});

export const toolProgressEventSchema = z.object({
  toolCallId: z.string(),
  progress: z.number().min(0).max(100).optional(),
  message: z.string().optional(),
  chunk: z.unknown().optional(),
  timestamp: z.number().int().positive()
});

export const toolExecutionEventSchema = z.discriminatedUnion('type', [
  z.object({ type: z.literal('tool_started'), call: toolCallSchema }),
  z.object({ type: z.literal('tool_progress'), event: toolProgressEventSchema }),
  z.object({ type: z.literal('tool_completed'), result: toolResultSchema })
]);

export type ToolMeta = z.infer<typeof toolMetaSchema>;
export type ToolCall = z.infer<typeof toolCallSchema>;
export type ToolResult = z.infer<typeof toolResultSchema>;
export type ToolProgressEvent = z.infer<typeof toolProgressEventSchema>;
export type ToolExecutionEvent = z.infer<typeof toolExecutionEventSchema>;

export interface PermissionEvaluationContext {
  role: 'user' | 'system' | 'admin';
  requiresApproval?: boolean;
  conversationTags?: string[];
  approvedTools?: string[];
  deniedTools?: string[];
}

export interface ToolCancellationToken {
  signal: AbortSignal;
  reason?: string;
}

export interface ToolExecutionContext {
  sessionId: string;
  turnId: string;
  signal: AbortSignal;
  role?: 'user' | 'system' | 'admin';
  conversationState?: Record<string, unknown>;
  approvedTools?: string[];
  deniedTools?: string[];
  emitProgress?: (event: ToolProgressEvent) => void;
  cancellationToken?: ToolCancellationToken;
}

export interface ToolDefinition<I = unknown, O = unknown> {
  meta: ToolMeta;
  inputSchema: z.ZodType<I>;
  outputSchema: z.ZodType<O>;
  resultSchema?: z.ZodType<O>;
  execute(input: I, ctx: ToolExecutionContext): Promise<O>;
}

export interface StreamingToolDefinition<I = unknown, O = unknown> extends ToolDefinition<I, O> {
  executeStream(input: I, ctx: ToolExecutionContext): AsyncGenerator<unknown, O, void>;
}

export function isStreamingToolDefinition(definition: ToolDefinition): definition is StreamingToolDefinition {
  return typeof (definition as Partial<StreamingToolDefinition>).executeStream === 'function';
}

export interface ToolRegistry {
  register(definition: ToolDefinition): void;
  update?(name: string, definition: ToolDefinition): void;
  remove?(name: string): void;
  getByName(name: string): ToolDefinition | undefined;
  list(): ToolDefinition[];
  getPermissionRequirement?(name: string): PermissionDecision | undefined;
}
