import { beforeEach, expect, test } from "vitest";
import { useThinkStore } from "./thinkStore";

beforeEach(() => useThinkStore.getState().reset());

const ev = (turn_id: string, index: number, type = "model.thinking") => ({
  channel: "trace", type: "event",
  payload: { payload: { type, turn_id, step: "direct", index, text: `t${index}`, truncated: false, chars: 2, elapsed_ms: 10 } },
});

test("onThinkState sets enabled/supported/reason", () => {
  useThinkStore.getState().onThinkState({ channel: "control", type: "think.state", payload: { enabled: true, supported: false, reason: "r" } });
  const s = useThinkStore.getState();
  expect([s.enabled, s.supported, s.reason]).toEqual([true, false, "r"]);
});

test("onTrace groups by turn in arrival order", () => {
  const s = useThinkStore.getState();
  s.onTrace(ev("a", 0)); s.onTrace(ev("b", 0)); s.onTrace(ev("a", 1));
  const st = useThinkStore.getState();
  expect(st.turnOrder).toEqual(["a", "b"]);
  expect(st.eventsByTurn.a.map((e) => e.index)).toEqual([0, 1]);
  expect(st.eventsByTurn.a[0]).toMatchObject({ turnId: "a", step: "direct", text: "t0", elapsedMs: 10 });
});

test("non-thinking trace payloads are ignored", () => {
  useThinkStore.getState().onTrace(ev("a", 0, "model.token"));
  expect(useThinkStore.getState().turnOrder).toEqual([]);
});

test("voice command sets a notice cleared by turn end", () => {
  const s = useThinkStore.getState();
  s.onVoiceCommand({ channel: "chat", type: "voice_command", payload: { command: "rethink", phrase: "think harder" } });
  expect(useThinkStore.getState().voiceNotice).toContain("“think harder”");
  s.clearVoiceNotice();
  expect(useThinkStore.getState().voiceNotice).toBeNull();
});

test("select sets selectedTurnId", () => {
  useThinkStore.getState().select("a");
  expect(useThinkStore.getState().selectedTurnId).toBe("a");
});
