import { z } from 'zod';
import { StructuredLogger, sanitizeError } from './observability.js';
import { modelRequestSchema, modelResponseSchema } from './schemas.js';
const DEFAULT_REQUEST_SIZE_LIMIT_BYTES = 1024 * 1024;
const MAX_STREAM_BUFFER_BYTES = 4 * 1024 * 1024;
export class BaseProvider {
    config;
    logger;
    constructor(config) {
        this.config = config;
        this.logger = new StructuredLogger(`provider.${this.constructor.name}`, process.env.ZYGOS_DEBUG === '1');
    }
    supportsModel(model) {
        if (!this.config.models || this.config.models.length === 0) {
            return true;
        }
        return this.config.models.some((candidate) => model.toLowerCase().includes(candidate.toLowerCase()));
    }
    estimateTokens(messages, model) {
        const chars = messages.reduce((acc, message) => acc + message.content.length, 0);
        const promptTokens = Math.ceil(chars / 4);
        const modelContextWindow = this.capabilities.maxContextTokens;
        const maxOutputTokens = Math.min(2048, Math.floor(modelContextWindow * 0.2));
        return {
            promptTokens,
            maxOutputTokens,
            totalEstimate: promptTokens + maxOutputTokens,
            modelContextWindow
        };
    }
    get timeoutMs() {
        return this.config.timeoutMs ?? 45_000;
    }
    get requestSizeLimitBytes() {
        return this.config.requestSizeLimitBytes ?? DEFAULT_REQUEST_SIZE_LIMIT_BYTES;
    }
    validateAndSanitizeRequest(request) {
        const parsed = modelRequestSchema.parse(request);
        const sanitizedMessages = parsed.messages.map((message) => ({
            ...message,
            content: this.sanitizeUserInput(message.content)
        }));
        return {
            ...parsed,
            messages: sanitizedMessages
        };
    }
    sanitizeUserInput(text) {
        return text.replaceAll('\u0000', '').replace(/\r\n/g, '\n').trim();
    }
    buildHeaders(additional) {
        return {
            'content-type': 'application/json',
            ...(this.config.headers ?? {}),
            ...(additional ?? {})
        };
    }
    async postJson(url, body, headers, responseSchema) {
        this.assertEndpointSecurity(url);
        const serialized = JSON.stringify(body);
        if (serialized.length > this.requestSizeLimitBytes) {
            throw this.error('budget_exhausted', `Request body exceeded size limit (${this.requestSizeLimitBytes} bytes).`);
        }
        const response = await this.fetchWithTimeout(url, {
            method: 'POST',
            headers: this.buildHeaders(headers),
            body: serialized,
            keepalive: true
        });
        if (!response.ok) {
            const responseBody = await response.text();
            throw this.classifyHttpError(response.status, responseBody);
        }
        const parsed = await this.safeJson(response);
        if (responseSchema) {
            return responseSchema.parse(parsed);
        }
        return parsed;
    }
    async fetchWithTimeout(url, init) {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), this.timeoutMs);
        try {
            return await fetch(url, {
                ...init,
                signal: controller.signal
            });
        }
        catch (error) {
            if (controller.signal.aborted) {
                throw this.error('network_timeout', `Provider request timed out after ${this.timeoutMs}ms.`);
            }
            throw this.error('recoverable_provider_error', `Network request failed: ${error instanceof Error ? error.message : String(error)}`);
        }
        finally {
            clearTimeout(timeout);
        }
    }
    async *streamSSE(response, parser) {
        if (!response.body) {
            throw this.error('provider_unavailable', 'Provider response body is empty.');
        }
        const decoder = new TextDecoder();
        let buffer = '';
        let doneSeen = false;
        for await (const chunk of response.body) {
            buffer += decoder.decode(chunk, { stream: true });
            if (buffer.length > MAX_STREAM_BUFFER_BYTES) {
                throw this.error('malformed_response', 'Streaming response exceeded max buffer limit.');
            }
            const frames = buffer.split('\n\n');
            buffer = frames.pop() ?? '';
            for (const frame of frames) {
                const dataLines = frame
                    .split('\n')
                    .filter((line) => line.startsWith('data:'))
                    .map((line) => line.replace(/^data:\s*/, ''));
                for (const dataLine of dataLines) {
                    if (dataLine === '[DONE]') {
                        doneSeen = true;
                        yield { type: 'done', response: { text: '', finishReason: 'stop' } };
                        continue;
                    }
                    for (const event of parser(dataLine)) {
                        if (event.type === 'done') {
                            doneSeen = true;
                        }
                        yield event;
                    }
                }
            }
        }
        if (buffer.trim().length > 0) {
            this.logger.log('warn', 'Leftover streaming buffer detected after stream end.', { preview: buffer.slice(0, 100) });
        }
        if (!doneSeen) {
            throw this.error('provider_unavailable', 'Streaming response ended before completion marker was received.');
        }
    }
    responseFromText(text, usage, nativeResponse) {
        return modelResponseSchema.parse({
            text,
            usage,
            nativeResponse
        });
    }
    async safeJson(response) {
        const text = await response.text();
        if (!text.trim()) {
            throw this.error('malformed_response', 'Empty JSON response received from provider.');
        }
        try {
            return JSON.parse(text);
        }
        catch {
            throw this.error('malformed_response', 'Provider returned malformed JSON response.');
        }
    }
    classifyHttpError(status, body) {
        const normalizedBody = body?.slice(0, 500);
        if (status === 401 || status === 403) {
            return this.error('authentication_error', `Authentication failed with status ${status}.`, { status, body: normalizedBody });
        }
        if (status === 429) {
            return this.error('rate_limited', 'Provider rate limit exceeded.', { status, body: normalizedBody });
        }
        if (status >= 500) {
            return this.error('provider_unavailable', `Provider unavailable (HTTP ${status}).`, { status, body: normalizedBody });
        }
        return this.error('recoverable_provider_error', `Provider request failed with HTTP ${status}.`, {
            status,
            body: normalizedBody
        });
    }
    error(code, message, details) {
        return sanitizeError({ code, message, details });
    }
    assertEndpointSecurity(url) {
        const parsed = new URL(url);
        if (parsed.protocol === 'https:') {
            return;
        }
        const isLocalhost = ['localhost', '127.0.0.1'].includes(parsed.hostname);
        if (parsed.protocol === 'http:' && isLocalhost) {
            return;
        }
        throw this.error('authentication_error', `Refusing insecure non-local endpoint: ${parsed.origin}`);
    }
}
//# sourceMappingURL=base.provider.js.map