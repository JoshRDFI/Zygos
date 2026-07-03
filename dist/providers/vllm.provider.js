import { OpenAIProvider } from './openai.provider.js';
export class VllmProvider extends OpenAIProvider {
    key = 'vllm';
    capabilities = {
        streaming: true,
        toolCalling: true,
        maxContextTokens: 128_000,
        protocols: ['openai_chat']
    };
    constructor(config) {
        super({
            ...config,
            baseUrl: config.baseUrl ?? 'http://127.0.0.1:8000/v1'
        });
    }
}
//# sourceMappingURL=vllm.provider.js.map