import { z } from 'zod';
export declare const permissionDecisionSchema: z.ZodEnum<["allow", "deny", "require_approval"]>;
export type PermissionDecision = z.infer<typeof permissionDecisionSchema>;
export declare const toolParallelHintSchema: z.ZodDefault<z.ZodEnum<["safe", "unsafe"]>>;
export type ToolParallelHint = z.infer<typeof toolParallelHintSchema>;
export declare const resultFormatSchema: z.ZodDefault<z.ZodEnum<["json", "text", "binary"]>>;
export type ResultFormat = z.infer<typeof resultFormatSchema>;
export declare const toolMetaSchema: z.ZodObject<{
    name: z.ZodString;
    description: z.ZodString;
    version: z.ZodDefault<z.ZodString>;
    timeoutMs: z.ZodDefault<z.ZodNumber>;
    concurrency: z.ZodDefault<z.ZodEnum<["safe_parallel", "serial_only"]>>;
    destructive: z.ZodDefault<z.ZodBoolean>;
    permission: z.ZodDefault<z.ZodEnum<["allow", "ask", "deny"]>>;
    aliases: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
    permissionRequirement: z.ZodOptional<z.ZodEnum<["allow", "deny", "require_approval"]>>;
    parallelHint: z.ZodOptional<z.ZodDefault<z.ZodEnum<["safe", "unsafe"]>>>;
    dependencies: z.ZodOptional<z.ZodArray<z.ZodString, "many">>;
    resultFormat: z.ZodOptional<z.ZodDefault<z.ZodEnum<["json", "text", "binary"]>>>;
    maxResultBytes: z.ZodOptional<z.ZodNumber>;
    retry: z.ZodOptional<z.ZodObject<{
        attempts: z.ZodDefault<z.ZodNumber>;
        backoffMs: z.ZodDefault<z.ZodNumber>;
    }, "strip", z.ZodTypeAny, {
        attempts: number;
        backoffMs: number;
    }, {
        attempts?: number | undefined;
        backoffMs?: number | undefined;
    }>>;
    fallbackTool: z.ZodOptional<z.ZodString>;
}, "strip", z.ZodTypeAny, {
    timeoutMs: number;
    name: string;
    description: string;
    version: string;
    concurrency: "safe_parallel" | "serial_only";
    destructive: boolean;
    permission: "allow" | "deny" | "ask";
    aliases: string[];
    retry?: {
        attempts: number;
        backoffMs: number;
    } | undefined;
    permissionRequirement?: "allow" | "deny" | "require_approval" | undefined;
    parallelHint?: "safe" | "unsafe" | undefined;
    dependencies?: string[] | undefined;
    resultFormat?: "json" | "text" | "binary" | undefined;
    maxResultBytes?: number | undefined;
    fallbackTool?: string | undefined;
}, {
    name: string;
    description: string;
    timeoutMs?: number | undefined;
    retry?: {
        attempts?: number | undefined;
        backoffMs?: number | undefined;
    } | undefined;
    version?: string | undefined;
    concurrency?: "safe_parallel" | "serial_only" | undefined;
    destructive?: boolean | undefined;
    permission?: "allow" | "deny" | "ask" | undefined;
    aliases?: string[] | undefined;
    permissionRequirement?: "allow" | "deny" | "require_approval" | undefined;
    parallelHint?: "safe" | "unsafe" | undefined;
    dependencies?: string[] | undefined;
    resultFormat?: "json" | "text" | "binary" | undefined;
    maxResultBytes?: number | undefined;
    fallbackTool?: string | undefined;
}>;
export declare const toolCallSchema: z.ZodObject<{
    id: z.ZodString;
    name: z.ZodString;
    input: z.ZodRecord<z.ZodString, z.ZodUnknown>;
}, "strip", z.ZodTypeAny, {
    name: string;
    id: string;
    input: Record<string, unknown>;
}, {
    name: string;
    id: string;
    input: Record<string, unknown>;
}>;
export declare const normalizedToolErrorSchema: z.ZodObject<{
    code: z.ZodString;
    message: z.ZodString;
    retryable: z.ZodDefault<z.ZodBoolean>;
    details: z.ZodOptional<z.ZodRecord<z.ZodString, z.ZodUnknown>>;
}, "strip", z.ZodTypeAny, {
    code: string;
    message: string;
    retryable: boolean;
    details?: Record<string, unknown> | undefined;
}, {
    code: string;
    message: string;
    retryable?: boolean | undefined;
    details?: Record<string, unknown> | undefined;
}>;
export declare const toolResultSchema: z.ZodObject<{
    toolCallId: z.ZodString;
    ok: z.ZodBoolean;
    output: z.ZodOptional<z.ZodUnknown>;
    error: z.ZodOptional<z.ZodString>;
    normalizedError: z.ZodOptional<z.ZodObject<{
        code: z.ZodString;
        message: z.ZodString;
        retryable: z.ZodDefault<z.ZodBoolean>;
        details: z.ZodOptional<z.ZodRecord<z.ZodString, z.ZodUnknown>>;
    }, "strip", z.ZodTypeAny, {
        code: string;
        message: string;
        retryable: boolean;
        details?: Record<string, unknown> | undefined;
    }, {
        code: string;
        message: string;
        retryable?: boolean | undefined;
        details?: Record<string, unknown> | undefined;
    }>>;
    durationMs: z.ZodNumber;
    synthetic: z.ZodDefault<z.ZodBoolean>;
    partial: z.ZodDefault<z.ZodBoolean>;
    bytes: z.ZodOptional<z.ZodNumber>;
    warnings: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
}, "strip", z.ZodTypeAny, {
    toolCallId: string;
    ok: boolean;
    durationMs: number;
    synthetic: boolean;
    partial: boolean;
    warnings: string[];
    output?: unknown;
    error?: string | undefined;
    normalizedError?: {
        code: string;
        message: string;
        retryable: boolean;
        details?: Record<string, unknown> | undefined;
    } | undefined;
    bytes?: number | undefined;
}, {
    toolCallId: string;
    ok: boolean;
    durationMs: number;
    output?: unknown;
    error?: string | undefined;
    normalizedError?: {
        code: string;
        message: string;
        retryable?: boolean | undefined;
        details?: Record<string, unknown> | undefined;
    } | undefined;
    synthetic?: boolean | undefined;
    partial?: boolean | undefined;
    bytes?: number | undefined;
    warnings?: string[] | undefined;
}>;
export declare const toolProgressEventSchema: z.ZodObject<{
    toolCallId: z.ZodString;
    progress: z.ZodOptional<z.ZodNumber>;
    message: z.ZodOptional<z.ZodString>;
    chunk: z.ZodOptional<z.ZodUnknown>;
    timestamp: z.ZodNumber;
}, "strip", z.ZodTypeAny, {
    toolCallId: string;
    timestamp: number;
    message?: string | undefined;
    progress?: number | undefined;
    chunk?: unknown;
}, {
    toolCallId: string;
    timestamp: number;
    message?: string | undefined;
    progress?: number | undefined;
    chunk?: unknown;
}>;
export declare const toolExecutionEventSchema: z.ZodDiscriminatedUnion<"type", [z.ZodObject<{
    type: z.ZodLiteral<"tool_started">;
    call: z.ZodObject<{
        id: z.ZodString;
        name: z.ZodString;
        input: z.ZodRecord<z.ZodString, z.ZodUnknown>;
    }, "strip", z.ZodTypeAny, {
        name: string;
        id: string;
        input: Record<string, unknown>;
    }, {
        name: string;
        id: string;
        input: Record<string, unknown>;
    }>;
}, "strip", z.ZodTypeAny, {
    type: "tool_started";
    call: {
        name: string;
        id: string;
        input: Record<string, unknown>;
    };
}, {
    type: "tool_started";
    call: {
        name: string;
        id: string;
        input: Record<string, unknown>;
    };
}>, z.ZodObject<{
    type: z.ZodLiteral<"tool_progress">;
    event: z.ZodObject<{
        toolCallId: z.ZodString;
        progress: z.ZodOptional<z.ZodNumber>;
        message: z.ZodOptional<z.ZodString>;
        chunk: z.ZodOptional<z.ZodUnknown>;
        timestamp: z.ZodNumber;
    }, "strip", z.ZodTypeAny, {
        toolCallId: string;
        timestamp: number;
        message?: string | undefined;
        progress?: number | undefined;
        chunk?: unknown;
    }, {
        toolCallId: string;
        timestamp: number;
        message?: string | undefined;
        progress?: number | undefined;
        chunk?: unknown;
    }>;
}, "strip", z.ZodTypeAny, {
    type: "tool_progress";
    event: {
        toolCallId: string;
        timestamp: number;
        message?: string | undefined;
        progress?: number | undefined;
        chunk?: unknown;
    };
}, {
    type: "tool_progress";
    event: {
        toolCallId: string;
        timestamp: number;
        message?: string | undefined;
        progress?: number | undefined;
        chunk?: unknown;
    };
}>, z.ZodObject<{
    type: z.ZodLiteral<"tool_completed">;
    result: z.ZodObject<{
        toolCallId: z.ZodString;
        ok: z.ZodBoolean;
        output: z.ZodOptional<z.ZodUnknown>;
        error: z.ZodOptional<z.ZodString>;
        normalizedError: z.ZodOptional<z.ZodObject<{
            code: z.ZodString;
            message: z.ZodString;
            retryable: z.ZodDefault<z.ZodBoolean>;
            details: z.ZodOptional<z.ZodRecord<z.ZodString, z.ZodUnknown>>;
        }, "strip", z.ZodTypeAny, {
            code: string;
            message: string;
            retryable: boolean;
            details?: Record<string, unknown> | undefined;
        }, {
            code: string;
            message: string;
            retryable?: boolean | undefined;
            details?: Record<string, unknown> | undefined;
        }>>;
        durationMs: z.ZodNumber;
        synthetic: z.ZodDefault<z.ZodBoolean>;
        partial: z.ZodDefault<z.ZodBoolean>;
        bytes: z.ZodOptional<z.ZodNumber>;
        warnings: z.ZodDefault<z.ZodArray<z.ZodString, "many">>;
    }, "strip", z.ZodTypeAny, {
        toolCallId: string;
        ok: boolean;
        durationMs: number;
        synthetic: boolean;
        partial: boolean;
        warnings: string[];
        output?: unknown;
        error?: string | undefined;
        normalizedError?: {
            code: string;
            message: string;
            retryable: boolean;
            details?: Record<string, unknown> | undefined;
        } | undefined;
        bytes?: number | undefined;
    }, {
        toolCallId: string;
        ok: boolean;
        durationMs: number;
        output?: unknown;
        error?: string | undefined;
        normalizedError?: {
            code: string;
            message: string;
            retryable?: boolean | undefined;
            details?: Record<string, unknown> | undefined;
        } | undefined;
        synthetic?: boolean | undefined;
        partial?: boolean | undefined;
        bytes?: number | undefined;
        warnings?: string[] | undefined;
    }>;
}, "strip", z.ZodTypeAny, {
    type: "tool_completed";
    result: {
        toolCallId: string;
        ok: boolean;
        durationMs: number;
        synthetic: boolean;
        partial: boolean;
        warnings: string[];
        output?: unknown;
        error?: string | undefined;
        normalizedError?: {
            code: string;
            message: string;
            retryable: boolean;
            details?: Record<string, unknown> | undefined;
        } | undefined;
        bytes?: number | undefined;
    };
}, {
    type: "tool_completed";
    result: {
        toolCallId: string;
        ok: boolean;
        durationMs: number;
        output?: unknown;
        error?: string | undefined;
        normalizedError?: {
            code: string;
            message: string;
            retryable?: boolean | undefined;
            details?: Record<string, unknown> | undefined;
        } | undefined;
        synthetic?: boolean | undefined;
        partial?: boolean | undefined;
        bytes?: number | undefined;
        warnings?: string[] | undefined;
    };
}>]>;
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
export declare function isStreamingToolDefinition(definition: ToolDefinition): definition is StreamingToolDefinition;
export interface ToolRegistry {
    register(definition: ToolDefinition): void;
    update?(name: string, definition: ToolDefinition): void;
    remove?(name: string): void;
    getByName(name: string): ToolDefinition | undefined;
    list(): ToolDefinition[];
    getPermissionRequirement?(name: string): PermissionDecision | undefined;
}
//# sourceMappingURL=tool.types.d.ts.map