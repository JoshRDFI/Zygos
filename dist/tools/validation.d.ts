import { z } from 'zod';
import { type ResultFormat, type ToolResult } from '../types/tool.types.js';
export interface ValidationOptions {
    maxResultBytes?: number;
    format?: ResultFormat;
}
export declare function sanitizeToolOutput(value: unknown): unknown;
export declare function validateResultFormat(output: unknown, format: ResultFormat): void;
export declare function validateAndCoerceOutput<T>(schema: z.ZodType<T>, output: unknown): T;
export declare function enforceResultSize(output: unknown, maxBytes?: number): number;
export declare function normalizeErrorResult(toolCallId: string, error: unknown, durationMs: number, code?: string, retryable?: boolean, details?: Record<string, unknown>): ToolResult;
export declare function finalizeSuccessResult(result: Omit<ToolResult, 'bytes'>, opts?: ValidationOptions): ToolResult;
//# sourceMappingURL=validation.d.ts.map