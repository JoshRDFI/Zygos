import type { ModelRequest, OpenAIChatMessage, OpenAIChatRequest, ProtocolMessage } from '../../types/provider.types.js';
/** Converts internal protocol messages into OpenAI chat messages. */
export declare function toOpenAIChatMessages(messages: ProtocolMessage[]): OpenAIChatMessage[];
/** Converts a generic model request into an OpenAI-compatible chat completion request. */
export declare function toOpenAIChatRequest(request: ModelRequest): OpenAIChatRequest;
/** Heuristic protocol detector for OpenAI-compatible model families. */
export declare function detectOpenAICompatibleProtocol(model: string): boolean;
//# sourceMappingURL=openai.adapter.d.ts.map