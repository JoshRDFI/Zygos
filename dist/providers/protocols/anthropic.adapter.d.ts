import type { AnthropicMessage, AnthropicMessagesRequest, ModelRequest, ProtocolMessage } from '../../types/provider.types.js';
/** Converts internal protocol messages to Anthropic format, including collapsed system prompts. */
export declare function toAnthropicMessages(messages: ProtocolMessage[]): {
    system?: string;
    messages: AnthropicMessage[];
};
/** Converts a generic model request into an Anthropic messages request payload. */
export declare function toAnthropicMessagesRequest(request: ModelRequest): AnthropicMessagesRequest;
/** Heuristic protocol detector for Anthropic model families. */
export declare function detectAnthropicProtocol(model: string): boolean;
//# sourceMappingURL=anthropic.adapter.d.ts.map