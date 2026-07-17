import { expect, test } from "vitest";
import { PlaybackScheduler, type AudioCtxLike, type BufferSourceLike } from "./playbackScheduler";
import { float32ToInt16LE } from "./pcm";

function fakeCtx(now = 0) {
  const starts: number[] = [];
  const ctx: AudioCtxLike & { starts: number[]; now: number } = {
    starts,
    now,
    get currentTime() { return this.now; },
    sampleRate: 24000,
    createBuffer: (_ch, length) => ({ getChannelData: () => new Float32Array(length) }),
    createBufferSource: (): BufferSourceLike => ({
      buffer: null,
      connect: () => {},
      start: (when: number) => starts.push(when),
    }),
  };
  return ctx;
}

test("schedules chunks back-to-back (gapless) from currentTime", () => {
  const ctx = fakeCtx(1.0);
  const sched = new PlaybackScheduler(ctx, {});
  const chunk = float32ToInt16LE(new Float32Array(24000)).buffer; // exactly 1 second @ 24k
  sched.enqueue(chunk as ArrayBuffer);
  sched.enqueue(chunk as ArrayBuffer);
  expect(ctx.starts[0]).toBeCloseTo(1.0, 5);
  expect(ctx.starts[1]).toBeCloseTo(2.0, 5); // right after the first
});

test("reset drops the cursor so the next chunk starts at currentTime", () => {
  const ctx = fakeCtx(0);
  const sched = new PlaybackScheduler(ctx, {});
  sched.enqueue(float32ToInt16LE(new Float32Array(12000)).buffer as ArrayBuffer); // 0.5s
  sched.reset();
  ctx.now = 5.0;
  sched.enqueue(float32ToInt16LE(new Float32Array(12000)).buffer as ArrayBuffer);
  expect(ctx.starts[1]).toBeCloseTo(5.0, 5);
});
