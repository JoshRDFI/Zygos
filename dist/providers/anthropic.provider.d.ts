import { BaseProvider } from './base.provider.js';
import type { ModelRequest, ModelResponse, ProviderCapabilities, ProviderConfig, ProviderStreamEvent } from '../types/provider.types.js';
export declare class AnthropicProvider extends BaseProvider {
    readonly key: "anthropic";
    readonly capabilities: ProviderCapabilities;
    constructor(config: ProviderConfig);
    complete(request: ModelRequest): Promise<ModelResponse>;
    stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void>;
    private parseStreamFrame;
}
//# sourceMappingURL=anthropic.provider.d.ts.map