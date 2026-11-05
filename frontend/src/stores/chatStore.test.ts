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

// ---- RFC-0013 phase 2: answering model + loading (frames captured from the backend) ----
import frames from "./fixtures/model-turn-frames.json";
import type { Frame } from "../client/types";

const feed = (fs: unknown[]) => fs.forEach((f) => useChatStore.getState().onFrame(f as Frame));
const chat = (fs: unknown[]) => (fs as { channel: string }[]).filter((f) => f.channel === "chat");

test("model.loading is subscribed to by the session", async () => {
  const { CHAT_FRAME_TYPES } = await import("./chatStore");
  expect(CHAT_FRAME_TYPES).toContain("model.loading");
});

test("model.loading marks the running turn until the first token", () => {
  const all = chat(frames.turn_with_load_all_frames);
  feed(all.slice(0, 2)); // turn.start, model.loading
  expect(useChatStore.getState().messages.at(-1)).toMatchObject({ streaming: true, loadingModel: "qwen3:8b" });
  feed([all[2]]); // first token
  expect(useChatStore.getState().messages.at(-1)!.loadingModel).toBeNull();
});

test("model.loading for another turn_id is ignored", () => {
  const all = chat(frames.turn_with_load_all_frames);
  feed([all[0]]);
  feed([{ channel: "chat", type: "model.loading", payload: { turn_id: "other", provider: "ollama", model: "x" } }]);
  expect(useChatStore.getState().messages.at(-1)!.loadingModel ?? null).toBeNull();
});

test("turn.end clears loading and records the answering model", () => {
  const all = chat(frames.turn_with_load_all_frames);
  feed([all[0], all[1], all.at(-1)]); // no token: loading must still clear
  expect(useChatStore.getState().messages.at(-1)).toMatchObject({
    streaming: false, loadingModel: null, answeredBy: "qwen3:8b", text: "savedanswer",
  });
});

test("turn.end with model null leaves answeredBy empty", () => {
  feed([{ channel: "chat", type: "turn.start", payload: { turn_id: "t" } },
    { channel: "chat", type: "turn.end", payload: { text: "x", model: null, category: "chat" } }]);
  expect(useChatStore.getState().messages.at(-1)!.answeredBy ?? null).toBeNull();
});

test("an error frame clears a pending loading note", () => {
  const all = chat(frames.turn_with_load_all_frames);
  feed(all.slice(0, 2));
  feed([{ channel: "chat", type: "error", payload: { message: "boom" } }]);
  expect(useChatStore.getState().messages.some((m) => m.loadingModel)).toBe(false);
});
