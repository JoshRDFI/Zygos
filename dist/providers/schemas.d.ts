import { z } from 'zod';
export declare const protocolMessageSchema: z.ZodObject<{
    role: z.ZodEnum<["system", "user", "assistant", "tool"]>;
    content: z.ZodString;
    name: z.ZodOptional<z.ZodString>;
    toolCallId: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    role: "user" | "system" | "assistant" | "tool";
    content: string;
    name?: string | undefined;
    toolCallId?: string | undefined;
}, {
    role: "user" | "system" | "assistant" | "tool";
    content: string;
    name?: string | undefined;
    toolCallId?: string | undefined;
}>;
export declare const modelRequestSchema: z.ZodObject<{
    sessionId: z.ZodString;
    model: z.ZodString;
    messages: z.ZodArray<z.ZodObject<{
        role: z.ZodEnum<["system", "user", "assistant", "tool"]>;
        content: z.ZodString;
        name: z.ZodOptional<z.ZodString>;
        toolCallId: z.ZodOptional<z.ZodString>;
    }, "strip", z.ZodTypeAny, {
        role: "user" | "system" | "assistant" | "tool";
        content: string;
        name?: string | undefined;
        toolCallId?: string | undefined;
    }, {
        role: "user" | "system" | "assistant" | "tool";
        content: string;
        name?: string | undefined;
        toolCallId?: string | undefined;
    }>, "many">;
    temperature: z.ZodOptional<z.ZodNumber>;
    maxOutputTokens: z.ZodOptional<z.ZodNumber>;
    stream: z.ZodOptional<z.ZodBoolean>;
    tools: z.ZodOptional<z.ZodArray<z.ZodRecord<z.ZodString, z.ZodUnknown>, "many">>;
    metadata: z.ZodOptional<z.ZodRecord<z.ZodString, z.ZodUnknown>>;
}, "strip", z.ZodTypeAny, {
    model: string;
    sessionId: string;
    messages: {
        role: "user" | "system" | "assistant" | "tool";
        content: string;
        name?: string | undefined;
        toolCallId?: string | undefined;
    }[];
    temperature?: number | undefined;
    maxOutputTokens?: number | undefined;
    stream?: boolean | undefined;
    tools?: Record<string, unknown>[] | undefined;
    metadata?: Record<string, unknown> | undefined;
}, {
    model: string;
    sessionId: string;
    messages: {
        role: "user" | "system" | "assistant" | "tool";
        content: string;
        name?: string | undefined;
        toolCallId?: string | undefined;
    }[];
    temperature?: number | undefined;
    maxOutputTokens?: number | undefined;
    stream?: boolean | undefined;
    tools?: Record<string, unknown>[] | undefined;
    metadata?: Record<string, unknown> | undefined;
}>;
export declare const usageStatsSchema: z.ZodObject<{
    inputTokens: z.ZodOptional<z.ZodNumber>;
    outputTokens: z.ZodOptional<z.ZodNumber>;
    totalTokens: z.ZodOptional<z.ZodNumber>;
}, "strip", z.ZodTypeAny, {
    inputTokens?: number | undefined;
    outputTokens?: number | undefined;
    totalTokens?: number | undefined;
}, {
    inputTokens?: number | undefined;
    outputTokens?: number | undefined;
    totalTokens?: number | undefined;
}>;
export declare const modelResponseSchema: z.ZodObject<{
    text: z.ZodString;
    finishReason: z.ZodOptional<z.ZodString>;
    usage: z.ZodOptional<z.ZodObject<{
        inputTokens: z.ZodOptional<z.ZodNumber>;
        outputTokens: z.ZodOptional<z.ZodNumber>;
        totalTokens: z.ZodOptional<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        inputTokens?: number | undefined;
        outputTokens?: number | undefined;
        totalTokens?: number | undefined;
    }, {
        inputTokens?: number | undefined;
        outputTokens?: number | undefined;
        totalTokens?: number | undefined;
    }>>;
    nativeResponse: z.ZodOptional<z.ZodUnknown>;
}, "strip", z.ZodTypeAny, {
    text: string;
    usage?: {
        inputTokens?: number | undefined;
        outputTokens?: number | undefined;
        totalTokens?: number | undefined;
    } | undefined;
    finishReason?: string | undefined;
    nativeResponse?: unknown;
}, {
    text: string;
    usage?: {
        inputTokens?: number | undefined;
        outputTokens?: number | undefined;
        totalTokens?: number | undefined;
    } | undefined;
    finishReason?: string | undefined;
    nativeResponse?: unknown;
}>;
export declare const openAIResponseSchema: z.ZodObject<{
    choices: z.ZodOptional<z.ZodArray<z.ZodObject<{
        message: z.ZodOptional<z.ZodObject<{
            content: z.ZodOptional<z.ZodString>;
        }, "strip", z.ZodTypeAny, {
            content?: string | undefined;
        }, {
            content?: string | undefined;
        }>>;
        delta: z.ZodOptional<z.ZodObject<{
            content: z.ZodOptional<z.ZodString>;
        }, "strip", z.ZodTypeAny, {
            content?: string | undefined;
        }, {
            content?: string | undefined;
        }>>;
        finish_reason: z.ZodOptional<z.ZodNullable<z.ZodString>>;
    }, "strip", z.ZodTypeAny, {
        message?: {
            content?: string | undefined;
        } | undefined;
        delta?: {
            content?: string | undefined;
        } | undefined;
        finish_reason?: string | null | undefined;
    }, {
        message?: {
            content?: string | undefined;
        } | undefined;
        delta?: {
            content?: string | undefined;
        } | undefined;
        finish_reason?: string | null | undefined;
    }>, "many">>;
    usage: z.ZodOptional<z.ZodObject<{
        prompt_tokens: z.ZodOptional<z.ZodNumber>;
        completion_tokens: z.ZodOptional<z.ZodNumber>;
        total_tokens: z.ZodOptional<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        prompt_tokens?: number | undefined;
        completion_tokens?: number | undefined;
        total_tokens?: number | undefined;
    }, {
        prompt_tokens?: number | undefined;
        completion_tokens?: number | undefined;
        total_tokens?: number | undefined;
    }>>;
}, "strip", z.ZodTypeAny, {
    usage?: {
        prompt_tokens?: number | undefined;
        completion_tokens?: number | undefined;
        total_tokens?: number | undefined;
    } | undefined;
    choices?: {
        message?: {
            content?: string | undefined;
        } | undefined;
        delta?: {
            content?: string | undefined;
        } | undefined;
        finish_reason?: string | null | undefined;
    }[] | undefined;
}, {
    usage?: {
        prompt_tokens?: number | undefined;
        completion_tokens?: number | undefined;
        total_tokens?: number | undefined;
    } | undefined;
    choices?: {
        message?: {
            content?: string | undefined;
        } | undefined;
        delta?: {
            content?: string | undefined;
        } | undefined;
        finish_reason?: string | null | undefined;
    }[] | undefined;
}>;
export declare const anthropicResponseSchema: z.ZodObject<{
    content: z.ZodOptional<z.ZodArray<z.ZodObject<{
        type: z.ZodString;
        text: z.ZodOptional<z.ZodString>;
    }, "strip", z.ZodTypeAny, {
        type: string;
        text?: string | undefined;
    }, {
        type: string;
        text?: string | undefined;
    }>, "many">>;
    usage: z.ZodOptional<z.ZodObject<{
        input_tokens: z.ZodOptional<z.ZodNumber>;
        output_tokens: z.ZodOptional<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        input_tokens?: number | undefined;
        output_tokens?: number | undefined;
    }, {
        input_tokens?: number | undefined;
        output_tokens?: number | undefined;
    }>>;
    stop_reason: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    usage?: {
        input_tokens?: number | undefined;
        output_tokens?: number | undefined;
    } | undefined;
    content?: {
        type: string;
        text?: string | undefined;
    }[] | undefined;
    stop_reason?: string | undefined;
}, {
    usage?: {
        input_tokens?: number | undefined;
        output_tokens?: number | undefined;
    } | undefined;
    content?: {
        type: string;
        text?: string | undefined;
    }[] | undefined;
    stop_reason?: string | undefined;
}>;
export declare const ollamaResponseSchema: z.ZodObject<{
    message: z.ZodOptional<z.ZodObject<{
        content: z.ZodOptional<z.ZodString>;
    }, "strip", z.ZodTypeAny, {
        content?: string | undefined;
    }, {
        content?: string | undefined;
    }>>;
    done_reason: z.ZodOptional<z.ZodString>;
    prompt_eval_count: z.ZodOptional<z.ZodNumber>;
    eval_count: z.ZodOptional<z.ZodNumber>;
    done: z.ZodOptional<z.ZodBoolean>;
}, "strip", z.ZodTypeAny, {
    message?: {
        content?: string | undefined;
    } | undefined;
    done?: boolean | undefined;
    done_reason?: string | undefined;
    prompt_eval_count?: number | undefined;
    eval_count?: number | undefined;
}, {
    message?: {
        content?: string | undefined;
    } | undefined;
    done?: boolean | undefined;
    done_reason?: string | undefined;
    prompt_eval_count?: number | undefined;
    eval_count?: number | undefined;
}>;
//# sourceMappingURL=schemas.d.ts.map