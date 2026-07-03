import { OpenAIProvider } from './openai.provider.js';
import type { ProviderCapabilities, ProviderConfig } from '../types/provider.types.js';
export declare class VllmProvider extends OpenAIProvider {
    readonly key: "vllm";
    readonly capabilities: ProviderCapabilities;
    constructor(config: ProviderConfig);
}
//# sourceMappingURL=vllm.provider.d.ts.map