import { beforeEach, expect, test } from "vitest";
import { useChatStore } from "./chatStore";

beforeEach(() => useChatStore.getState().reset());

test("streaming turn: start, tokens, end", () => {
  const s = useChatStore.getState();
  s.addUser("hi");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t1" } });
  s.onFrame({ channel: "chat", type: "token", payload: { text: "he" } });
  s.onFrame({ channel: "chat", type: "token", payload: { text: "llo" } });
  s.onFrame({ channel: "chat", type: "turn.end", payload: { text: "hello" } });

  const msgs = useChatStore.getState().messages;
  expect(msgs.map((m) => m.role)).toEqual(["user", "assistant"]);
  expect(msgs[1]).toMatchObject({ role: "assistant", text: "hello", streaming: false });
});

test("error frame surfaces an assistant message", () => {
  const s = useChatStore.getState();
  s.onFrame({ channel: "chat", type: "error", payload: { message: "generation failed" } });
  const last = useChatStore.getState().messages.at(-1)!;
  expect(last.role).toBe("assistant");
  expect(last.text).toContain("generation failed");
});

test("a committed STT final becomes a user message", () => {
  const s = useChatStore.getState();
  s.onFrame({ channel: "chat", type: "final", payload: { text: "hello from voice" } });
  const last = useChatStore.getState().messages.at(-1)!;
  expect(last).toEqual({ role: "user", text: "hello from voice", streaming: false });
});

test("turn.start carries turn id, think and the pending question", () => {
  const s = useChatStore.getState();
  s.addUser("q");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t1", think: true, rethink_of: null } });
  const m = useChatStore.getState().messages[1];
  expect(m.turnId).toBe("t1");
  expect(m.think).toBe(true);
  expect(m.rethinkOf).toBeNull();
  expect(m.question).toBe("q");
});

test("turn.end records thinking_ms and unsupported reason", () => {
  const s = useChatStore.getState();
  s.addUser("q");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t1" } });
  s.onFrame({ channel: "chat", type: "turn.end", payload: { text: "a", think: true, thinking_ms: 4200, think_unsupported_reason: "nope" } });
  const m = useChatStore.getState().messages[1];
  expect(m.thinkingMs).toBe(4200);
  expect(m.thinkUnsupportedReason).toBe("nope");
});

test("addReask sets the question without adding a user bubble", () => {
  const s = useChatStore.getState();
  s.addUser("old");
  s.addReask("q");
  expect(useChatStore.getState().messages).toHaveLength(1);
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t2", rethink_of: "t1" } });
  const msgs = useChatStore.getState().messages;
  expect(msgs.map((m) => m.role)).toEqual(["user", "assistant"]);
  expect(msgs[1].question).toBe("q");
  expect(msgs[1].rethinkOf).toBe("t1");
});

test("voice_command frames do not change messages", () => {
  const s = useChatStore.getState();
  s.addUser("q");
  s.onFrame({ channel: "chat", type: "voice_command", payload: { command: "rethink", phrase: "think harder" } });
  expect(useChatStore.getState().messages).toHaveLength(1);
});

test("an error after turn.start releases the stuck streaming message (I3)", () => {
  const s = useChatStore.getState();
  s.addUser("q");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t1", think: true } });
  s.onFrame({ channel: "chat", type: "error", payload: { message: "generation failed" } });
  const msgs = useChatStore.getState().messages;
  expect(msgs.find((m) => m.turnId === "t1")!.streaming).toBe(false);
  expect(msgs.some((m) => m.streaming)).toBe(false);
  expect(msgs.at(-1)!.text).toContain("generation failed");
});

test("a voice rethink copies the question from the rethought turn (M2)", () => {
  useChatStore.setState({
    messages: [
      { role: "user", text: "why is the sky blue?", streaming: false },
      { role: "assistant", text: "scattering", streaming: false, turnId: "t1", question: "why is the sky blue?" },
      { role: "user", text: "Think harder.", streaming: false },
    ],
  });
  useChatStore.getState().onFrame({
    channel: "chat", type: "turn.start", payload: { turn_id: "t2", think: true, rethink_of: "t1" },
  });
  expect(useChatStore.getState().messages.at(-1)!.question).toBe("why is the sky blue?");
});
