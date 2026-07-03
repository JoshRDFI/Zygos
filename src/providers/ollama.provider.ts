import { BaseProvider } from './base.provider.js';
import { toOpenAIChatMessages } from './protocols/openai.adapter.js';
import { ollamaResponseSchema } from './schemas.js';
import type {
  ModelRequest,
  ModelResponse,
  ProviderCapabilities,
  ProviderConfig,
  ProviderStreamEvent
} from '../types/provider.types.js';

export class OllamaProvider extends BaseProvider {
  readonly key = 'ollama' as const;

  readonly capabilities: ProviderCapabilities = {
    streaming: true,
    toolCalling: false,
    maxContextTokens: 32_000,
    protocols: ['openai_chat']
  };

  constructor(config: ProviderConfig) {
    super(config);
  }

  async complete(request: ModelRequest): Promise<ModelResponse> {
    const sanitized = this.validateAndSanitizeRequest(request);
    const baseUrl = this.config.baseUrl ?? 'http://127.0.0.1:11434';
    const response = await this.postJson(
      `${baseUrl}/api/chat`,
      {
        model: sanitized.model,
        messages: toOpenAIChatMessages(sanitized.messages),
        stream: false,
        options: {
          temperature: sanitized.temperature
        }
      },
      undefined,
      ollamaResponseSchema
    );

    return {
      text: response.message?.content ?? '',
      finishReason: response.done_reason,
      usage: {
        inputTokens: response.prompt_eval_count,
        outputTokens: response.eval_count,
        totalTokens: (response.prompt_eval_count ?? 0) + (response.eval_count ?? 0)
      },
      nativeResponse: response
    };
  }

  async *stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void> {
    const sanitized = this.validateAndSanitizeRequest(request);
    const baseUrl = this.config.baseUrl ?? 'http://127.0.0.1:11434';

    let response: Response;
    try {
      response = await this.fetchWithTimeout(`${baseUrl}/api/chat`, {
        method: 'POST',
        headers: this.buildHeaders(),
        body: JSON.stringify({
          model: sanitized.model,
          messages: toOpenAIChatMessages(sanitized.messages),
          stream: true,
          options: {
            temperature: sanitized.temperature
          }
        }),
        keepalive: true
      });
    } catch (error) {
      yield { type: 'error', error: this.error('recoverable_provider_error', String((error as Error).message ?? error)) };
      return;
    }

    if (!response.ok || !response.body) {
      yield {
        type: 'error',
        error: this.classifyHttpError(response.status, await response.text())
      };
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let doneSeen = false;

    for await (const chunk of response.body as unknown as AsyncIterable<Uint8Array>) {
      buffer += decoder.decode(chunk, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.trim()) {
          continue;
        }

        try {
          const parsed = ollamaResponseSchema.parse(JSON.parse(line));
          const delta = parsed.message?.content;
          if (delta) {
            yield { type: 'delta', text: delta };
          }

          if (parsed.done) {
            doneSeen = true;
            yield {
              type: 'done',
              response: {
                text: '',
                finishReason: parsed.done_reason,
                usage: {
                  inputTokens: parsed.prompt_eval_count,
                  outputTokens: parsed.eval_count,
                  totalTokens: (parsed.prompt_eval_count ?? 0) + (parsed.eval_count ?? 0)
                }
              }
            };
          }
        } catch {
          this.logger.log('warn', 'Malformed Ollama stream frame dropped.');
        }
      }
    }

    if (!doneSeen) {
      yield {
        type: 'error',
        error: this.error('provider_unavailable', 'Ollama stream ended without completion marker.')
      };
    }
  }
}
