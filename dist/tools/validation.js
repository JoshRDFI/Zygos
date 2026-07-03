import { z } from 'zod';
import { redactSensitive } from '../providers/observability.js';
import { toolResultSchema } from '../types/tool.types.js';
const DEFAULT_MAX_RESULT_BYTES = 512_000;
function sizeof(value) {
    if (value instanceof Uint8Array) {
        return value.byteLength;
    }
    if (typeof value === 'string') {
        return Buffer.byteLength(value, 'utf8');
    }
    return Buffer.byteLength(JSON.stringify(value ?? null), 'utf8');
}
export function sanitizeToolOutput(value) {
    if (typeof value === 'string') {
        return value.replaceAll('\u0000', '').slice(0, 200_000);
    }
    return redactSensitive(value);
}
export function validateResultFormat(output, format) {
    if (format === 'binary' && !(output instanceof Uint8Array)) {
        throw new Error('Expected binary output (Uint8Array).');
    }
    if (format === 'text' && typeof output !== 'string') {
        throw new Error('Expected text output (string).');
    }
    if (format === 'json' && output instanceof Uint8Array) {
        throw new Error('Binary output is not allowed for JSON format.');
    }
}
export function validateAndCoerceOutput(schema, output) {
    return schema.parse(output);
}
export function enforceResultSize(output, maxBytes = DEFAULT_MAX_RESULT_BYTES) {
    const bytes = sizeof(output);
    if (bytes > maxBytes) {
        throw new Error(`Tool output exceeds size limit (${bytes} > ${maxBytes} bytes).`);
    }
    return bytes;
}
export function normalizeErrorResult(toolCallId, error, durationMs, code = 'tool_execution_error', retryable = false, details) {
    const message = error instanceof Error ? error.message : String(error);
    const stack = error instanceof Error && error.stack ? error.stack.split('\n').slice(0, 3).join('\n') : undefined;
    return toolResultSchema.parse({
        toolCallId,
        ok: false,
        error: message.slice(0, 500),
        normalizedError: {
            code,
            message: message.slice(0, 500),
            retryable,
            details: {
                ...(details ?? {}),
                ...(stack ? { stack } : {})
            }
        },
        durationMs,
        synthetic: true
    });
}
export function finalizeSuccessResult(result, opts = {}) {
    const format = opts.format ?? 'json';
    const sanitized = sanitizeToolOutput(result.output);
    validateResultFormat(sanitized, format);
    const bytes = enforceResultSize(sanitized, opts.maxResultBytes ?? DEFAULT_MAX_RESULT_BYTES);
    return toolResultSchema.parse({
        ...result,
        output: sanitized,
        bytes
    });
}
//# sourceMappingURL=validation.js.map