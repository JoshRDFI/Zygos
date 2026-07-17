import { expect, test } from "vitest";
import { CaptureController, type CaptureSink } from "./captureController";
import { TAG_IN } from "./pcm";

function fakeSink(): CaptureSink & { controls: { type: string }[]; binary: Uint8Array[] } {
  const controls: { type: string }[] = [];
  const binary: Uint8Array[] = [];
  return {
    controls, binary,
    sendControl: (type) => controls.push({ type }),
    sendBinary: (bytes) => binary.push(bytes),
  };
}

test("start emits audio.start and enters capturing; stop emits audio.endpoint", () => {
  const sink = fakeSink();
  const c = new CaptureController(sink);
  expect(c.state).toBe("idle");
  c.start();
  expect(c.state).toBe("capturing");
  expect(sink.controls).toEqual([{ type: "audio.start" }]);
  c.stop();
  expect(c.state).toBe("idle");
  expect(sink.controls.map((x) => x.type)).toEqual(["audio.start", "audio.endpoint"]);
});

test("double start and idle stop are guarded (no duplicate control frames)", () => {
  const sink = fakeSink();
  const c = new CaptureController(sink);
  c.stop(); // idle stop: no-op
  c.start();
  c.start(); // double start: no-op
  expect(sink.controls.map((x) => x.type)).toEqual(["audio.start"]);
});

test("pushFrames sends tagged 16k PCM only while capturing", () => {
  const sink = fakeSink();
  const c = new CaptureController(sink);
  c.pushFrames(new Float32Array([0.5, 0.5]), 48000); // idle: ignored
  expect(sink.binary).toHaveLength(0);
  c.start();
  c.pushFrames(new Float32Array(48), 48000); // 48 @48k -> 16 @16k -> 32 bytes + 1 tag
  expect(sink.binary).toHaveLength(1);
  expect(sink.binary[0][0]).toBe(TAG_IN);
  expect(sink.binary[0].byteLength).toBe(16 * 2 + 1);
  c.stop();
  c.pushFrames(new Float32Array(48), 48000); // idle again: ignored
  expect(sink.binary).toHaveLength(1);
});
