import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createPlayback } from "./playbackAdapter";

// Minimal AudioContext fake: records every buffer source's start time.
class FakeAudioContext {
  static last: FakeAudioContext | null = null;
  currentTime = 0;
  sampleRate = 24000;
  destination = {};
  starts: number[] = [];
  gainTargets: number[] = [];
  constructor() { FakeAudioContext.last = this; }
  createGain() {
    return {
      gain: { value: 1, setTargetAtTime: (v: number) => { this.gainTargets.push(v); } },
      connect: () => {},
    };
  }
  createBuffer(_ch: number, length: number) {
    return { getChannelData: () => new Float32Array(length) };
  }
  createBufferSource() {
    return {
      buffer: null, onended: null,
      connect: () => {}, disconnect: () => {},
      start: (when: number) => { this.starts.push(when); },
      stop: () => {},
    };
  }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

const second = () => new Int16Array(24000).buffer; // 1 s @ 24 kHz mono s16

beforeEach(() => vi.stubGlobal("AudioContext", FakeAudioContext));
afterEach(() => vi.unstubAllGlobals());

function setup() {
  const p = createPlayback();
  p.setEnabled(true);
  return { p, ctx: FakeAudioContext.last! };
}

test("back-to-back utterances queue: the next begins at the previous cursor", () => {
  const { p, ctx } = setup();
  p.begin();
  p.enqueue(second());
  p.end(); // the prefix is still playing (0..1 s)
  ctx.currentTime = 0.3;
  p.begin(); // the reply starts while the prefix plays
  p.enqueue(second());
  expect(ctx.starts).toEqual([0, 1]); // not 0.3 — no overlap
});

test("after the previous utterance has finished, the next starts at currentTime", () => {
  const { p, ctx } = setup();
  p.begin();
  p.enqueue(second());
  p.end();
  ctx.currentTime = 5;
  p.begin();
  p.enqueue(second());
  expect(ctx.starts[1]).toBe(5);
});

test("begin still restores full volume", () => {
  const { p, ctx } = setup();
  p.duck(0.2);
  p.begin();
  expect(ctx.gainTargets.at(-1)).toBe(1.0);
});

test("interrupt drops the queue: the next utterance starts at currentTime", () => {
  const { p, ctx } = setup();
  p.begin();
  p.enqueue(second());
  p.enqueue(second()); // queued to 2 s
  ctx.currentTime = 0.5;
  p.interrupt();
  p.begin();
  p.enqueue(second());
  expect(ctx.starts.at(-1)).toBe(0.5);
});
