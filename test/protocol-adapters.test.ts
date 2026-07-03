import test from 'node:test';
import assert from 'node:assert/strict';
import { toOpenAIChatMessages, toOpenAIChatRequest, detectOpenAICompatibleProtocol } from '../src/providers/protocols/openai.adapter.js';
import { toAnthropicMessages, toAnthropicMessagesRequest, detectAnthropicProtocol } from '../src/providers/protocols/anthropic.adapter.js';

test('OpenAI adapter sanitizes and maps messages', () => {
  const messages = toOpenAIChatMessages([
    { role: 'user', content: 'hello\u0000\r\nworld ' },
    { role: 'tool', content: 'result', name: 'demo', toolCallId: 'call_1' }
  ]);

  assert.equal(messages[0].content, 'hello\nworld');
  assert.equal(messages[1].tool_call_id, 'call_1');
});

test('OpenAI adapter builds request payload', () => {
  const request = toOpenAIChatRequest({
    sessionId: 's1',
    model: 'gpt-4o-mini',
    messages: [{ role: 'user', content: 'hello' }],
    stream: true,
    maxOutputTokens: 100
  });

  assert.equal(request.model, 'gpt-4o-mini');
  assert.equal(request.stream, true);
  assert.equal(request.max_tokens, 100);
});

test('Anthropic adapter converts system and tool messages', () => {
  const converted = toAnthropicMessages([
    { role: 'system', content: 'system prompt' },
    { role: 'tool', content: 'tool output', name: 'search' },
    { role: 'user', content: 'hello' }
  ]);

  assert.equal(converted.system, 'system prompt');
  assert.equal(converted.messages[0].role, 'assistant');
  assert.match(converted.messages[0].content[0].text, /tool:search/);
});

test('Anthropic adapter builds request payload', () => {
  const request = toAnthropicMessagesRequest({
    sessionId: 's2',
    model: 'claude-3-5-haiku-latest',
    messages: [{ role: 'user', content: 'hi' }],
    maxOutputTokens: 256,
    stream: false
  });

  assert.equal(request.max_tokens, 256);
  assert.equal(request.messages[0].role, 'user');
});

test('Protocol detection helpers identify model families', () => {
  assert.equal(detectOpenAICompatibleProtocol('gpt-4o'), true);
  assert.equal(detectOpenAICompatibleProtocol('llama3.1:8b'), true);
  assert.equal(detectAnthropicProtocol('claude-3-opus'), true);
  assert.equal(detectAnthropicProtocol('unknown-model'), false);
});
