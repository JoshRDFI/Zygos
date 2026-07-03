import { z } from 'zod';
export const protocolMessageSchema = z.object({
    role: z.enum(['system', 'user', 'assistant', 'tool']),
    content: z.string().trim().min(1),
    name: z.string().trim().min(1).optional(),
    toolCallId: z.string().trim().min(1).optional()
});
export const modelRequestSchema = z.object({
    sessionId: z.string().trim().min(1),
    model: z.string().trim().min(1),
    messages: z.array(protocolMessageSchema).min(1),
    temperature: z.number().min(0).max(2).optional(),
    maxOutputTokens: z.number().int().positive().max(8192).optional(),
    stream: z.boolean().optional(),
    tools: z.array(z.record(z.unknown())).optional(),
    metadata: z.record(z.unknown()).optional()
});
export const usageStatsSchema = z.object({
    inputTokens: z.number().int().nonnegative().optional(),
    outputTokens: z.number().int().nonnegative().optional(),
    totalTokens: z.number().int().nonnegative().optional()
});
export const modelResponseSchema = z.object({
    text: z.string(),
    finishReason: z.string().optional(),
    usage: usageStatsSchema.optional(),
    nativeResponse: z.unknown().optional()
});
export const openAIResponseSchema = z.object({
    choices: z
        .array(z.object({
        message: z.object({ content: z.string().optional() }).optional(),
        delta: z.object({ content: z.string().optional() }).optional(),
        finish_reason: z.string().nullable().optional()
    }))
        .optional(),
    usage: z
        .object({
        prompt_tokens: z.number().int().nonnegative().optional(),
        completion_tokens: z.number().int().nonnegative().optional(),
        total_tokens: z.number().int().nonnegative().optional()
    })
        .optional()
});
export const anthropicResponseSchema = z.object({
    content: z.array(z.object({ type: z.string(), text: z.string().optional() })).optional(),
    usage: z
        .object({
        input_tokens: z.number().int().nonnegative().optional(),
        output_tokens: z.number().int().nonnegative().optional()
    })
        .optional(),
    stop_reason: z.string().optional()
});
export const ollamaResponseSchema = z.object({
    message: z.object({ content: z.string().optional() }).optional(),
    done_reason: z.string().optional(),
    prompt_eval_count: z.number().int().nonnegative().optional(),
    eval_count: z.number().int().nonnegative().optional(),
    done: z.boolean().optional()
});
//# sourceMappingURL=schemas.js.map