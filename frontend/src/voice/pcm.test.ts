import { expect, test } from "vitest";
import { TAG_IN, TAG_OUT, float32ToInt16LE, int16ToFloat32, resampleTo16k, tagFrame, readTag } from "./pcm";

test("float32 <-> int16 round-trips within quantization error", () => {
  const src = new Float32Array([0, 0.5, -0.5, 1, -1]);
  const bytes = float32ToInt16LE(src);
  expect(bytes.byteLength).toBe(src.length * 2);
  const back = int16ToFloat32(bytes.buffer as ArrayBuffer);
  for (let i = 0; i < src.length; i++) expect(back[i]).toBeCloseTo(src[i], 3);
});

test("float32ToInt16LE clamps out-of-range samples", () => {
  const bytes = float32ToInt16LE(new Float32Array([2, -2]));
  const view = new DataView(bytes.buffer);
  expect(view.getInt16(0, true)).toBe(32767);
  expect(view.getInt16(2, true)).toBe(-32767);
});

test("resampleTo16k is identity at 16k and halves length from 32k", () => {
  const at16 = new Float32Array([0.1, 0.2, 0.3]);
  const out16 = resampleTo16k(at16, 16000);
  expect(out16.length).toBe(3);
  expect(out16[0]).toBeCloseTo(0.1, 5);
  expect(out16[1]).toBeCloseTo(0.2, 5);
  expect(out16[2]).toBeCloseTo(0.3, 5);
  const at32 = new Float32Array([0, 0, 1, 1, 0, 0, 1, 1]);
  expect(resampleTo16k(at32, 32000).length).toBe(4);
});

test("resampleTo16k handles 48k and empty input", () => {
  expect(resampleTo16k(new Float32Array(480), 48000).length).toBe(160);
  expect(resampleTo16k(new Float32Array(0), 44100).length).toBe(0);
});

test("tagFrame prefixes one byte; readTag splits it back", () => {
  const body = new Uint8Array([1, 2, 3]);
  const framed = tagFrame(TAG_IN, body);
  expect(framed[0]).toBe(TAG_IN);
  expect(framed.byteLength).toBe(4);
  const { tag, body: out } = readTag(framed.buffer as ArrayBuffer);
  expect(tag).toBe(TAG_IN);
  expect(Array.from(new Uint8Array(out))).toEqual([1, 2, 3]);
  expect(readTag(tagFrame(TAG_OUT, body).buffer as ArrayBuffer).tag).toBe(TAG_OUT);
});
