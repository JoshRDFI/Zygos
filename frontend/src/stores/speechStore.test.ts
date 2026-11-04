import { beforeEach, expect, test } from "vitest";
import { formatSpeechTiming, useSpeechStore, type SpeechTimingView } from "./speechStore";
import type { Frame } from "../client/types";

const base: SpeechTimingView = {
  turnId: "t1", firstAudioMs: 1830, wordsAtStart: 14, rateWps: 52, gaps: 0, gapMs: 0, reason: "complete",
};
const frame = (payload: Record<string, unknown>) => ({ payload }) as unknown as Frame;

beforeEach(() => useSpeechStore.getState().reset());

test("format: clean start", () => {
  expect(formatSpeechTiming(base)).toBe("first word 1.8 s · started after 14 words at 52 w/s · no gaps");
});
test("format: gaps plural and singular", () => {
  expect(formatSpeechTiming({ ...base, gaps: 2, gapMs: 1300 })).toMatch(/· 2 gaps \(1\.3 s, estimated\)$/);
  expect(formatSpeechTiming({ ...base, gaps: 1, gapMs: 400 })).toContain("1 gap (");
});
test("format: nothing spoken, null rate, cancelled", () => {
  expect(formatSpeechTiming({ ...base, firstAudioMs: null })).toContain("nothing spoken");
  expect(formatSpeechTiming({ ...base, rateWps: null })).not.toContain(" at ");
  expect(formatSpeechTiming({ ...base, reason: "cancelled" })).toMatch(/ · cancelled$/);
  expect(formatSpeechTiming({ ...base, reason: "error" })).toMatch(/ · error$/);
});
test("store accepts flat payload, ignores others, caps at 20", () => {
  const s = useSpeechStore.getState();
  s.onTrace(frame({ type: "model.thinking", turn_id: "x" }));
  expect(useSpeechStore.getState().timings).toHaveLength(0);
  for (let i = 0; i < 25; i++)
    s.onTrace(frame({ type: "speech.timing", turn_id: `t${i}`, first_audio_ms: 100, words_at_start: 3,
      rate_wps: null, gaps: 0, gap_ms: 0, reason: "complete" }));
  const t = useSpeechStore.getState().timings;
  expect(t).toHaveLength(20);
  expect(t[0].turnId).toBe("t5");
  expect(t[19]).toMatchObject({ turnId: "t24", firstAudioMs: 100, rateWps: null });
});
