import { z } from 'zod';
export const permissionDecisionSchema = z.enum(['allow', 'deny', 'require_approval']);
export const toolParallelHintSchema = z.enum(['safe', 'unsafe']).default('unsafe');
export const resultFormatSchema = z.enum(['json', 'text', 'binary']).default('json');
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
export function isStreamingToolDefinition(definition) {
    return typeof definition.executeStream === 'function';
}
//# sourceMappingURL=tool.types.js.map