import { BaseProvider } from './base.provider.js';
import type { ModelRequest, ModelResponse, ProviderCapabilities, ProviderConfig, ProviderStreamEvent } from '../types/provider.types.js';
export declare class OllamaProvider extends BaseProvider {
    readonly key: "ollama";
    readonly capabilities: ProviderCapabilities;
    constructor(config: ProviderConfig);
    complete(request: ModelRequest): Promise<ModelResponse>;
    stream(request: ModelRequest): AsyncGenerator<ProviderStreamEvent, void, void>;
}
//# sourceMappingURL=ollama.provider.d.ts.map