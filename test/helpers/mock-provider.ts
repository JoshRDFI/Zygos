import type {
  ModelRequest,
  ModelResponse,
  Provider,
  ProviderCapabilities,
  ProviderConfig,
  ProviderStreamEvent,
  SupportedProviderKey,
  TokenEstimate
} from '../../src/types/provider.types.js';

export class MockProvider implements Provider {
  readonly capabilities: ProviderCapabilities = {
    streaming: true,
    toolCalling: true,
    maxContextTokens: 8192,
    protocols: ['openai_chat', 'anthropic_messages']
  };

  public attempts = 0;

  constructor(
    public readonly key: SupportedProviderKey,
    public readonly config: ProviderConfig,
    private readonly behavior: {
      failAttempts?: number;
      responseText?: string;
      streamErrorCode?: 'recoverable_provider_error' | 'provider_unavailable' | 'rate_limited';
      unsupportedModels?: string[];
    } = {}
  ) {}

  supportsModel(model: string): boolean {
    return !(this.behavior.unsupportedModels ?? []).includes(model);
  }

  estimateTokens(messages: ModelRequest['messages']): TokenEstimate {
    const chars = messages.reduce((sum, message) => sum + message.content.length, 0);
    return {
      promptTokens: Math.ceil(chars / 4),
      maxOutputTokens: 128,
      totalEstimate: Math.ceil(chars / 4) + 128,
      modelContextWindow: 8192
    };
  }

  async complete(): Promise<ModelResponse> {
    return { text: this.behavior.responseText ?? 'ok' };
  }

  async *stream(_request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void> {
    this.attempts += 1;

    if (this.behavior.failAttempts && this.attempts <= this.behavior.failAttempts) {
      yield {
        type: 'error',
        error: {
          code: this.behavior.streamErrorCode ?? 'recoverable_provider_error',
          message: 'simulated failure'
        }
      };
      return;
    }

    const responseText = this.behavior.responseText ?? 'mock-response';
    yield { type: 'delta', text: responseText };
    yield { type: 'done', response: { text: '' } };
  }
}
