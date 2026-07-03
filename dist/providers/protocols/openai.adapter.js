function sanitizeContent(content) {
    return content.replaceAll('\u0000', '').replace(/\r\n/g, '\n').trim();
}
/** Converts internal protocol messages into OpenAI chat messages. */
export function toOpenAIChatMessages(messages) {
    return messages.map((message) => ({
        role: message.role,
        content: sanitizeContent(message.content),
        ...(message.name ? { name: message.name } : {}),
        ...(message.toolCallId ? { tool_call_id: message.toolCallId } : {})
    }));
}
/** Converts a generic model request into an OpenAI-compatible chat completion request. */
export function toOpenAIChatRequest(request) {
    return {
        model: request.model,
        messages: toOpenAIChatMessages(request.messages),
        ...(request.temperature !== undefined ? { temperature: request.temperature } : {}),
        ...(request.maxOutputTokens !== undefined ? { max_tokens: request.maxOutputTokens } : {}),
        ...(request.stream !== undefined ? { stream: request.stream } : {}),
        ...(request.tools ? { tools: request.tools } : {})
    };
}
/** Heuristic protocol detector for OpenAI-compatible model families. */
export function detectOpenAICompatibleProtocol(model) {
    const normalized = model.toLowerCase();
    return (normalized.startsWith('gpt') ||
        normalized.includes('openai') ||
        normalized.includes('llama') ||
        normalized.includes('mistral') ||
        normalized.includes('qwen'));
}
//# sourceMappingURL=openai.adapter.js.map