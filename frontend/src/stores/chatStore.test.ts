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
  expect(msgs[1]).toEqual({ role: "assistant", text: "hello", streaming: false });
});

test("error frame surfaces an assistant message", () => {
  const s = useChatStore.getState();
  s.onFrame({ channel: "chat", type: "error", payload: { message: "generation failed" } });
  const last = useChatStore.getState().messages.at(-1)!;
  expect(last.role).toBe("assistant");
  expect(last.text).toContain("generation failed");
});
