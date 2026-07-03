import { z } from 'zod';
import { BaseProvider } from './base.provider.js';
import { toOpenAIChatRequest } from './protocols/openai.adapter.js';
import { openAIResponseSchema } from './schemas.js';
const openAIStreamFrameSchema = z.object({
    choices: z
        .array(z.object({
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
export class OpenAIProvider extends BaseProvider {
    key = 'openai';
    capabilities = {
        streaming: true,
        toolCalling: true,
        maxContextTokens: 128_000,
        protocols: ['openai_chat']
    };
    constructor(config) {
        super(config);
    }
    async complete(request) {
        const sanitized = this.validateAndSanitizeRequest(request);
        const apiKey = this.config.apiKey ?? process.env.OPENAI_API_KEY;
        if (!apiKey) {
            throw this.error('authentication_error', 'Missing OpenAI API key.');
        }
        const payload = toOpenAIChatRequest({ ...sanitized, stream: false });
        const baseUrl = this.config.baseUrl ?? 'https://api.openai.com/v1';
        const response = await this.postJson(`${baseUrl}/chat/completions`, payload, {
            authorization: `Bearer ${apiKey}`,
            ...(this.config.organization ? { 'OpenAI-Organization': this.config.organization } : {})
        }, openAIResponseSchema);
        const text = response.choices?.[0]?.message?.content ?? '';
        return this.responseFromText(text, this.toUsage(response.usage), response);
    }
    async *stream(request) {
        const sanitized = this.validateAndSanitizeRequest(request);
        const apiKey = this.config.apiKey ?? process.env.OPENAI_API_KEY;
        if (!apiKey) {
            yield { type: 'error', error: this.error('authentication_error', 'Missing OpenAI API key.') };
            return;
        }
        const payload = toOpenAIChatRequest({ ...sanitized, stream: true });
        const baseUrl = this.config.baseUrl ?? 'https://api.openai.com/v1';
        let response;
        try {
            response = await this.fetchWithTimeout(`${baseUrl}/chat/completions`, {
                method: 'POST',
                headers: this.buildHeaders({
                    authorization: `Bearer ${apiKey}`,
                    ...(this.config.organization ? { 'OpenAI-Organization': this.config.organization } : {})
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
            const parsed = openAIStreamFrameSchema.parse(JSON.parse(data));
            const delta = parsed.choices?.[0]?.delta?.content;
            const events = [];
            if (delta) {
                events.push({ type: 'delta', text: delta });
            }
            const finishReason = parsed.choices?.[0]?.finish_reason;
            if (finishReason) {
                events.push({ type: 'done', response: { text: '', finishReason } });
            }
            if (parsed.usage) {
                const usage = this.toUsage(parsed.usage);
                if (usage) {
                    events.push({ type: 'usage', usage });
                }
            }
            return events;
        }
        catch {
            this.logger.log('warn', 'Malformed OpenAI SSE frame dropped.');
            return [];
        }
    }
    toUsage(usage) {
        if (!usage) {
            return undefined;
        }
        return {
            inputTokens: usage.prompt_tokens,
            outputTokens: usage.completion_tokens,
            totalTokens: usage.total_tokens
        };
    }
}
//# sourceMappingURL=openai.provider.js.map