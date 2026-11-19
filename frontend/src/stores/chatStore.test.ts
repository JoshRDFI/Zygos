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

// ---- tool cards ----
const tf = (type: string, payload: Record<string, unknown>) => ({ channel: "tools", type, payload });
const startTurn = () => {
  const s = useChatStore.getState();
  s.addUser("go");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t1" } });
};
const cards = () => useChatStore.getState().messages.at(-1)!.tools ?? [];

test("call then result makes a done card on the assistant message", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("call", { call_id: "c1", tool: "web_search", arguments: { q: "x" }, server: "srv" }));
  expect(cards()[0]).toMatchObject({ callId: "c1", tool: "web_search", server: "srv", args: { q: "x" }, status: "running" });
  s.onFrame(tf("result", { call_id: "c1", tool: "web_search", ok: true, output: { n: 1 } }));
  expect(cards()).toHaveLength(1);
  expect(cards()[0]).toMatchObject({ status: "done", output: { n: 1 } });
});

test("a tool frame with no assistant message creates a streaming one", () => {
  useChatStore.getState().onFrame(tf("call", { call_id: "c1", tool: "t", arguments: {} }));
  const m = useChatStore.getState().messages.at(-1)!;
  expect(m).toMatchObject({ role: "assistant", streaming: true });
  expect(m.tools).toHaveLength(1);
});

test("permission before call keeps asking status", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", {
    call_id: "c1", tool: "t", args_summary: { a: 1 }, expires_in_s: 60, can_trust: true,
    server: "srv", server_tool: "t", where: "remote", address: "https://x", description: "d",
    claims: ["reads"], rule_note: "n",
    changed: { old_description: "o", new_description: "n", old_schema: 1, new_schema: 2 },
  }));
  s.onFrame(tf("call", { call_id: "c1", tool: "t", arguments: { a: 1 } }));
  const c = cards()[0];
  expect(cards()).toHaveLength(1);
  expect(c.status).toBe("asking");
  expect(c.permission).toMatchObject({
    argsSummary: { a: 1 }, expiresInS: 60, canTrust: true, server: "srv", serverTool: "t",
    where: "remote", address: "https://x", description: "d", claims: ["reads"], ruleNote: "n",
    changed: { oldDescription: "o", newDescription: "n", oldSchema: 1, newSchema: 2 },
  });
  expect(typeof c.permission!.askedAt).toBe("number");
});

test("permission.result trusted_tool then result done", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("call", { call_id: "c1", tool: "t", arguments: {} }));
  s.onFrame(tf("permission", { call_id: "c1", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: true }));
  s.onFrame(tf("permission.result", { call_id: "c1", outcome: "trusted_tool" }));
  expect(cards()[0]).toMatchObject({ status: "running", outcome: "trusted_tool" });
  s.onFrame(tf("result", { call_id: "c1", tool: "t", ok: true, output: "ok" }));
  expect(cards()[0].status).toBe("done");
});

test("denied result marks card denied; other failures are failed", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("result", { call_id: "c1", tool: "t", ok: false, error_code: "tool_permission_denied", error_message: "no" }));
  s.onFrame(tf("result", { call_id: "c2", tool: "t", ok: false, error_code: "boom", error_message: "bad" }));
  expect(cards()[0].status).toBe("denied");
  expect(cards()[1]).toMatchObject({ status: "failed", errorMessage: "bad" });
});

test("denying outcomes set status denied", () => {
  startTurn();
  const s = useChatStore.getState();
  for (const [i, o] of ["denied", "timed_out", "cancelled"].entries()) {
    s.onFrame(tf("permission", { call_id: `c${i}`, tool: "t", args_summary: {}, expires_in_s: 1, can_trust: false }));
    s.onFrame(tf("permission.result", { call_id: `c${i}`, outcome: o }));
  }
  expect(cards().map((c) => c.status)).toEqual(["denied", "denied", "denied"]);
});

test("two pending cards resolve independently", () => {
  startTurn();
  const s = useChatStore.getState();
  for (const id of ["a", "b"]) {
    s.onFrame(tf("permission", { call_id: id, tool: "t", args_summary: {}, expires_in_s: 60, can_trust: true }));
  }
  s.onFrame(tf("permission.result", { call_id: "a", outcome: "allowed" }));
  expect(cards().map((c) => [c.callId, c.status])).toEqual([["a", "running"], ["b", "asking"]]);
});

test("fallback prompt gets its own card and ends done or denied", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("call", { call_id: "c1", tool: "t", arguments: {} }));
  s.onFrame(tf("permission", { call_id: "c1:fb", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: false }));
  s.onFrame(tf("permission", { call_id: "c2:fb", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: false }));
  expect(cards().map((c) => c.callId)).toEqual(["c1", "c1:fb", "c2:fb"]);
  s.onFrame(tf("permission.result", { call_id: "c1:fb", outcome: "allowed" }));
  s.onFrame(tf("permission.result", { call_id: "c2:fb", outcome: "denied" }));
  expect(cards().map((c) => c.status)).toEqual(["running", "done", "denied"]);
});

test("open card cancelled on turn end", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", { call_id: "a", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: true }));
  s.onFrame({ channel: "chat", type: "turn.end", payload: { text: "x" } });
  expect(cards()[0]).toMatchObject({ status: "denied", outcome: "cancelled" });
});

test("cancelOpenPrompts marks asking cards cancelled", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", { call_id: "a", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: true }));
  s.onFrame(tf("call", { call_id: "b", tool: "t", arguments: {} }));
  s.cancelOpenPrompts();
  expect(cards().map((c) => c.status)).toEqual(["denied", "running"]);
  expect(cards()[0].outcome).toBe("cancelled");
});

test("unknown tools frame type and bad call_id are ignored", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("bogus", { call_id: "a" }));
  s.onFrame(tf("call", { tool: "t" }));
  s.onFrame(tf("call", { call_id: 5, tool: "t" }));
  expect(cards()).toHaveLength(0);
});

test("a call id reused by a later step starts a new card with a live prompt", () => {
  startTurn();
  const s = useChatStore.getState();
  // step 1: prompted, allowed once, ran
  s.onFrame(tf("call", { call_id: "call_0", tool: "find_tasks", arguments: { q: 1 } }));
  s.onFrame(tf("permission", { call_id: "call_0", tool: "find_tasks", args_summary: {}, expires_in_s: 60, can_trust: true }));
  s.onFrame(tf("permission.result", { call_id: "call_0", outcome: "allowed" }));
  s.onFrame(tf("result", { call_id: "call_0", tool: "find_tasks", ok: true, output: "one" }));
  // step 2 reuses the id
  s.onFrame(tf("call", { call_id: "call_0", tool: "find_tasks", arguments: { q: 2 } }));
  s.onFrame(tf("permission", { call_id: "call_0", tool: "find_tasks", args_summary: {}, expires_in_s: 60, can_trust: true }));
  expect(cards()).toHaveLength(2);
  expect(cards()[0]).toMatchObject({ args: { q: 1 }, status: "done", output: "one", outcome: "allowed" });
  expect(cards()[1]).toMatchObject({ args: { q: 2 }, status: "asking" });
  expect(cards()[1].outcome).toBeUndefined();
  s.onFrame(tf("permission.result", { call_id: "call_0", outcome: "denied" }));
  expect(cards().map((c) => c.status)).toEqual(["done", "denied"]);
});

test("a permission for an id whose prompt was already answered starts a new card", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", { call_id: "x:fb", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: false }));
  s.onFrame(tf("permission.result", { call_id: "x:fb", outcome: "allowed" }));
  s.onFrame(tf("permission", { call_id: "x:fb", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: false }));
  expect(cards().map((c) => [c.status, c.outcome])).toEqual([["done", "allowed"], ["asking", undefined]]);
});

test("a call frame for a running card still merges", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", { call_id: "c1", tool: "t", args_summary: {}, expires_in_s: 60, can_trust: false }));
  s.onFrame(tf("permission.result", { call_id: "c1", outcome: "allowed" }));
  s.onFrame(tf("call", { call_id: "c1", tool: "t", arguments: { a: 1 } }));
  expect(cards()).toHaveLength(1);
  expect(cards()[0]).toMatchObject({ status: "running", args: { a: 1 } });
});

test("a permission frame without expires_in_s gets the default 120 s window", () => {
  startTurn();
  const s = useChatStore.getState();
  s.onFrame(tf("permission", { call_id: "c1", tool: "t", args_summary: {}, can_trust: false }));
  s.onFrame(tf("permission", { call_id: "c2", tool: "t", args_summary: {}, expires_in_s: "soon", can_trust: false }));
  s.onFrame(tf("permission", { call_id: "c3", tool: "t", args_summary: {}, expires_in_s: -5, can_trust: false }));
  expect(cards().map((c) => c.permission!.expiresInS)).toEqual([120, 120, 120]);
});
