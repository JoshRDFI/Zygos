import { setTimeout as sleep } from 'node:timers/promises';
import { z } from 'zod';
import { StructuredLogger } from '../providers/observability.js';
import { ParallelExecutionOrchestrator } from './parallel-executor.js';
import { PermissionManager } from './permissions.js';
import { finalizeSuccessResult, normalizeErrorResult, validateAndCoerceOutput } from './validation.js';
import { isStreamingToolDefinition, toolCallSchema, toolExecutionEventSchema, toolResultSchema } from '../types/tool.types.js';
class ToolExecutionMetrics {
    counters = new Map();
    recordStarted(tool) {
        const state = this.counters.get(tool) ?? { started: 0, succeeded: 0, failed: 0, totalDurationMs: 0 };
        state.started += 1;
        this.counters.set(tool, state);
    }
    recordCompleted(tool, ok, durationMs) {
        const state = this.counters.get(tool) ?? { started: 0, succeeded: 0, failed: 0, totalDurationMs: 0 };
        state.totalDurationMs += Math.max(0, durationMs);
        if (ok)
            state.succeeded += 1;
        else
            state.failed += 1;
        this.counters.set(tool, state);
    }
    snapshot() {
        return Object.fromEntries([...this.counters.entries()].map(([tool, stats]) => {
            const completed = stats.succeeded + stats.failed;
            return [
                tool,
                {
                    started: stats.started,
                    succeeded: stats.succeeded,
                    failed: stats.failed,
                    avgDurationMs: completed > 0 ? stats.totalDurationMs / completed : 0
                }
            ];
        }));
    }
}
export class StreamingToolExecutor {
    registry;
    logger;
    permissions;
    orchestrator;
    metrics = new ToolExecutionMetrics();
    options;
    constructor(registry, opts = {}, permissions) {
        this.registry = registry;
        this.options = {
            concurrency: opts.concurrency ?? 4,
            defaultTimeoutMs: opts.defaultTimeoutMs ?? 30_000,
            progressChunkSize: opts.progressChunkSize ?? 1_024
        };
        this.logger = new StructuredLogger('tools.streaming-executor', false);
        this.permissions = permissions ?? new PermissionManager();
        this.orchestrator = new ParallelExecutionOrchestrator({ concurrency: this.options.concurrency });
    }
    getMetrics() {
        return this.metrics.snapshot();
    }
    async execute(call, ctx) {
        const stream = this.executeOneStream(call, ctx);
        let final = null;
        for await (const event of stream) {
            if (event.type === 'tool_completed') {
                final = event.result;
            }
        }
        if (!final) {
            return normalizeErrorResult(call.id, 'Tool execution did not produce a final result', 0, 'tool_execution_error');
        }
        return final;
    }
    async executeBatch(calls, ctx) {
        const out = [];
        for await (const event of this.executeBatchStream(calls, ctx)) {
            if (event.type === 'tool_completed') {
                out.push(event.result);
            }
        }
        return out;
    }
    async *executeBatchStream(calls, ctx) {
        const parsedCalls = calls.map((call) => toolCallSchema.parse(call));
        const nodes = parsedCalls.map((call) => {
            const def = this.registry.getByName(call.name);
            return {
                call,
                dependencies: def?.meta.dependencies ?? [],
                parallelSafe: def?.meta.concurrency === 'safe_parallel' || def?.meta.parallelHint === 'safe',
                resourceKey: def?.meta.name ?? call.name
            };
        });
        const eventBuffer = new Map();
        const runOne = async (call, runCtx) => {
            const bucket = [];
            eventBuffer.set(call.id, bucket);
            let result = null;
            for await (const event of this.executeOneStream(call, runCtx)) {
                bucket.push(event);
                if (event.type === 'tool_completed') {
                    result = event.result;
                }
            }
            return result ?? normalizeErrorResult(call.id, 'Missing tool completion result', 0, 'tool_execution_error');
        };
        const { results } = await this.orchestrator.execute(nodes, ctx, runOne);
        for (const call of parsedCalls) {
            const buffered = eventBuffer.get(call.id) ?? [];
            for (const event of buffered) {
                yield toolExecutionEventSchema.parse(event);
            }
        }
        return results;
    }
    async *executeOneStream(call, ctx) {
        const startedAt = Date.now();
        const parsedCall = toolCallSchema.parse(call);
        yield { type: 'tool_started', call: parsedCall };
        const def = this.registry.getByName(parsedCall.name);
        if (!def) {
            const result = normalizeErrorResult(parsedCall.id, `Unknown tool: ${parsedCall.name}`, Date.now() - startedAt, 'tool_not_found');
            yield { type: 'tool_completed', result };
            return result;
        }
        const permission = this.permissions.check(def.meta, ctx);
        if (!permission.allowed) {
            const result = normalizeErrorResult(parsedCall.id, permission.reason ?? 'Permission denied', Date.now() - startedAt, 'tool_permission_denied');
            yield { type: 'tool_completed', result };
            return result;
        }
        const retryPolicy = def.meta.retry ?? { attempts: 1, backoffMs: 250 };
        const maxAttempts = retryPolicy.attempts;
        let result = null;
        for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
            this.metrics.recordStarted(def.meta.name);
            const controller = new AbortController();
            const timeoutMs = def.meta.timeoutMs ?? this.options.defaultTimeoutMs;
            const timeoutId = setTimeout(() => controller.abort(`tool timeout after ${timeoutMs}ms`), timeoutMs);
            const onAbort = () => controller.abort('execution cancelled');
            ctx.signal.addEventListener('abort', onAbort, { once: true });
            ctx.cancellationToken?.signal.addEventListener('abort', onAbort, { once: true });
            try {
                const parsedInput = def.inputSchema.parse(parsedCall.input);
                const streamCtx = {
                    ...ctx,
                    signal: controller.signal
                };
                const abortPromise = new Promise((_resolve, reject) => {
                    const abortNow = () => reject(new Error(`tool aborted: ${String(controller.signal.reason ?? 'cancelled')}`));
                    if (controller.signal.aborted) {
                        abortNow();
                        return;
                    }
                    controller.signal.addEventListener('abort', abortNow, { once: true });
                });
                let output;
                if (isStreamingToolDefinition(def)) {
                    const chunks = [];
                    let textBuffer = '';
                    const iterator = def.executeStream(parsedInput, streamCtx);
                    while (true) {
                        const next = await Promise.race([iterator.next(), abortPromise]);
                        if (next.done) {
                            break;
                        }
                        const chunk = next.value;
                        chunks.push(chunk);
                        if (typeof chunk === 'string') {
                            textBuffer += chunk;
                            if (textBuffer.length >= this.options.progressChunkSize) {
                                const chunkText = textBuffer;
                                textBuffer = '';
                                yield {
                                    type: 'tool_progress',
                                    event: {
                                        toolCallId: parsedCall.id,
                                        message: 'Streaming chunk received',
                                        chunk: chunkText,
                                        timestamp: Date.now()
                                    }
                                };
                            }
                        }
                        else {
                            yield {
                                type: 'tool_progress',
                                event: {
                                    toolCallId: parsedCall.id,
                                    message: 'Streaming update',
                                    chunk,
                                    timestamp: Date.now()
                                }
                            };
                        }
                    }
                    if (textBuffer.length > 0) {
                        yield {
                            type: 'tool_progress',
                            event: {
                                toolCallId: parsedCall.id,
                                message: 'Streaming chunk received',
                                chunk: textBuffer,
                                timestamp: Date.now()
                            }
                        };
                    }
                    output = chunks.every((c) => typeof c === 'string') ? chunks.join('') : chunks;
                }
                else {
                    output = await Promise.race([def.execute(parsedInput, streamCtx), abortPromise]);
                }
                const outputSchema = (def.resultSchema ?? def.outputSchema);
                const coerced = validateAndCoerceOutput(outputSchema, output);
                result = finalizeSuccessResult({
                    toolCallId: parsedCall.id,
                    ok: true,
                    output: coerced,
                    durationMs: Date.now() - startedAt,
                    synthetic: false,
                    partial: false,
                    warnings: []
                }, {
                    format: def.meta.resultFormat ?? 'json',
                    maxResultBytes: def.meta.maxResultBytes
                });
                this.metrics.recordCompleted(def.meta.name, true, result.durationMs);
                break;
            }
            catch (error) {
                const aborted = controller.signal.aborted;
                const code = aborted ? 'tool_timeout' : 'tool_execution_error';
                const retryable = aborted || this.isTransientError(error);
                result = toolResultSchema.parse({
                    ...normalizeErrorResult(parsedCall.id, error, Date.now() - startedAt, code, retryable, {
                        attempt,
                        tool: def.meta.name
                    }),
                    partial: aborted,
                    warnings: aborted ? ['Execution interrupted due to timeout/cancellation'] : []
                });
                this.metrics.recordCompleted(def.meta.name, false, result.durationMs);
                if (!result.normalizedError?.retryable || attempt === maxAttempts) {
                    break;
                }
                const delay = retryPolicy.backoffMs * attempt;
                yield {
                    type: 'tool_progress',
                    event: {
                        toolCallId: parsedCall.id,
                        message: `Retry ${attempt + 1}/${maxAttempts} in ${delay}ms`,
                        progress: Math.min(99, Math.round((attempt / maxAttempts) * 100)),
                        timestamp: Date.now()
                    }
                };
                await sleep(delay);
            }
            finally {
                clearTimeout(timeoutId);
                ctx.signal.removeEventListener('abort', onAbort);
                ctx.cancellationToken?.signal.removeEventListener('abort', onAbort);
            }
        }
        if (result && !result.ok && def.meta.fallbackTool) {
            const fallback = this.registry.getByName(def.meta.fallbackTool);
            if (fallback) {
                this.logger.log('warn', 'Primary tool failed, fallback configured', {
                    primary: def.meta.name,
                    fallback: fallback.meta.name,
                    callId: parsedCall.id
                });
            }
        }
        const finalResult = result ?? normalizeErrorResult(parsedCall.id, 'Unknown execution failure', Date.now() - startedAt);
        yield { type: 'tool_completed', result: finalResult };
        return finalResult;
    }
    isTransientError(error) {
        if (error instanceof Error) {
            const message = error.message.toLowerCase();
            return message.includes('timeout') || message.includes('temporar') || message.includes('network');
        }
        return false;
    }
}
//# sourceMappingURL=streaming-executor.js.map