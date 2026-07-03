import { OpenAIProvider } from './openai.provider.js';
import type { ProviderCapabilities, ProviderConfig } from '../types/provider.types.js';

export class VllmProvider extends OpenAIProvider {
  readonly key = 'vllm' as const;

  readonly capabilities: ProviderCapabilities = {
    streaming: true,
    toolCalling: true,
    maxContextTokens: 128_000,
    protocols: ['openai_chat']
  };

  constructor(config: ProviderConfig) {
    super({
      ...config,
      baseUrl: config.baseUrl ?? 'http://127.0.0.1:8000/v1'
    });
  }
}
