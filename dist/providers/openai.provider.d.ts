import { BaseProvider } from './base.provider.js';
import type { ModelRequest, ModelResponse, ProviderCapabilities, ProviderConfig, ProviderStreamEvent } from '../types/provider.types.js';
export declare class OpenAIProvider extends BaseProvider {
    readonly key: 'openai' | 'vllm';
    readonly capabilities: ProviderCapabilities;
    constructor(config: ProviderConfig);
    complete(request: ModelRequest): Promise<ModelResponse>;
    stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void>;
    private parseStreamFrame;
    private toUsage;
}
//# sourceMappingURL=openai.provider.d.ts.map