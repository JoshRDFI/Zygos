import { z } from 'zod';
import { BaseProvider } from './base.provider.js';
import { toAnthropicMessagesRequest } from './protocols/anthropic.adapter.js';
import { anthropicResponseSchema } from './schemas.js';
const anthropicStreamFrameSchema = z.object({
    type: z.string().optional(),
    delta: z.object({ text: z.string().optional() }).optional(),
    usage: z
        .object({
        input_tokens: z.number().int().nonnegative().optional(),
        output_tokens: z.number().int().nonnegative().optional()
    })
        .optional()
});
export class AnthropicProvider extends BaseProvider {
    key = 'anthropic';
    capabilities = {
        streaming: true,
        toolCalling: true,
        maxContextTokens: 200_000,
        protocols: ['anthropic_messages']
    };
    constructor(config) {
        super(config);
    }
    async complete(request) {
        const sanitized = this.validateAndSanitizeRequest(request);
        const apiKey = this.config.apiKey ?? process.env.ANTHROPIC_API_KEY;
        if (!apiKey) {
            throw this.error('authentication_error', 'Missing Anthropic API key.');
        }
        const payload = toAnthropicMessagesRequest({ ...sanitized, stream: false });
        const baseUrl = this.config.baseUrl ?? 'https://api.anthropic.com/v1';
        const response = await this.postJson(`${baseUrl}/messages`, payload, {
            'x-api-key': apiKey,
            'anthropic-version': '2023-06-01'
        }, anthropicResponseSchema);
        const text = (response.content ?? [])
            .filter((block) => block.type === 'text' && block.text)
            .map((block) => block.text)
            .join('');
        return {
            text,
            finishReason: response.stop_reason,
            usage: {
                inputTokens: response.usage?.input_tokens,
                outputTokens: response.usage?.output_tokens,
                totalTokens: (response.usage?.input_tokens ?? 0) + (response.usage?.output_tokens ?? 0)
            },
            nativeResponse: response
        };
    }
    async *stream(request) {
        const sanitized = this.validateAndSanitizeRequest(request);
        const apiKey = this.config.apiKey ?? process.env.ANTHROPIC_API_KEY;
        if (!apiKey) {
            yield { type: 'error', error: this.error('authentication_error', 'Missing Anthropic API key.') };
            return;
        }
        const payload = toAnthropicMessagesRequest({ ...sanitized, stream: true });
        const baseUrl = this.config.baseUrl ?? 'https://api.anthropic.com/v1';
        let response;
        try {
            response = await this.fetchWithTimeout(`${baseUrl}/messages`, {
                method: 'POST',
                headers: this.buildHeaders({
                    'x-api-key': apiKey,
                    'anthropic-version': '2023-06-01'
                }),
                body: JSON.stringify(payload),
                keepalive: true
            });
        }
        catch (error) {
            yield { type: 'error', error: this.error('recoverable_provider_error', String(error.message ?? error)) };
            return;
        }
        if (!response.ok) {
            yield { type: 'error', error: this.classifyHttpError(response.status, await response.text()) };
            return;
        }
        try {
            for await (const event of this.streamSSE(response, (data) => this.parseStreamFrame(data))) {
                yield event;
            }
        }
        catch (error) {
            yield { type: 'error', error: this.error('provider_unavailable', error.message) };
        }
    }
    parseStreamFrame(data) {
        try {
            const parsed = anthropicStreamFrameSchema.parse(JSON.parse(data));
            const events = [];
            if (parsed.type === 'content_block_delta' && parsed.delta?.text) {
                events.push({ type: 'delta', text: parsed.delta.text });
            }
            if (parsed.type === 'message_delta' && parsed.usage) {
                const usage = parsed.usage;
                events.push({
                    type: 'usage',
                    usage: {
                        inputTokens: usage.input_tokens,
                        outputTokens: usage.output_tokens,
                        totalTokens: (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0)
                    }
                });
            }
            if (parsed.type === 'message_stop') {
                events.push({ type: 'done', response: { text: '', finishReason: 'stop' } });
            }
            return events;
        }
        catch {
            this.logger.log('warn', 'Malformed Anthropic SSE frame dropped.');
            return [];
        }
    }
}
//# sourceMappingURL=anthropic.provider.js.map