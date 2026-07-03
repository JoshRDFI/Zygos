import type {
  AnthropicMessage,
  AnthropicMessagesRequest,
  ModelRequest,
  ProtocolMessage
} from '../../types/provider.types.js';

function sanitizeContent(content: string): string {
  return content.replaceAll('\u0000', '').replace(/\r\n/g, '\n').trim();
}

/** Converts internal protocol messages to Anthropic format, including collapsed system prompts. */
export function toAnthropicMessages(messages: ProtocolMessage[]): {
  system?: string;
  messages: AnthropicMessage[];
} {
  let system: string | undefined;
  const converted: AnthropicMessage[] = [];

  for (const message of messages) {
    if (message.role === 'system') {
      const cleaned = sanitizeContent(message.content);
      if (!cleaned) {
        continue;
      }
      system = system ? `${system}\n${cleaned}` : cleaned;
      continue;
    }

    if (message.role === 'tool') {
      converted.push({
        role: 'assistant',
        content: [{ type: 'text', text: `[tool:${message.name ?? 'tool'}] ${sanitizeContent(message.content)}` }]
      });
      continue;
    }

    converted.push({
      role: message.role === 'assistant' ? 'assistant' : 'user',
      content: [{ type: 'text', text: sanitizeContent(message.content) }]
    });
  }

  return { system, messages: converted };
}

/** Converts a generic model request into an Anthropic messages request payload. */
export function toAnthropicMessagesRequest(request: ModelRequest): AnthropicMessagesRequest {
  const { system, messages } = toAnthropicMessages(request.messages);

  return {
    model: request.model,
    max_tokens: request.maxOutputTokens ?? 512,
    messages,
    ...(system ? { system } : {}),
    ...(request.temperature !== undefined ? { temperature: request.temperature } : {}),
    ...(request.stream !== undefined ? { stream: request.stream } : {}),
    ...(request.tools ? { tools: request.tools } : {})
  };
}

/** Heuristic protocol detector for Anthropic model families. */
export function detectAnthropicProtocol(model: string): boolean {
  const normalized = model.toLowerCase();
  return normalized.startsWith('claude') || normalized.includes('anthropic');
}
