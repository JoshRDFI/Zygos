export const TAG_IN = 0x00;
export const TAG_OUT = 0x01;

export function float32ToInt16LE(frames: Float32Array): Uint8Array {
  const out = new Uint8Array(frames.length * 2);
  const view = new DataView(out.buffer);
  for (let i = 0; i < frames.length; i++) {
    const s = Math.max(-1, Math.min(1, frames[i]));
    view.setInt16(i * 2, Math.round(s * 32767), true);
  }
  return out;
}

export function int16ToFloat32(bytes: ArrayBuffer): Float32Array {
  const view = new DataView(bytes);
  const n = Math.floor(bytes.byteLength / 2);
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true) / 32767;
  return out;
}

export function resampleTo16k(input: Float32Array, inputRate: number): Float32Array {
  if (inputRate === 16000 || input.length === 0) return input;
  const ratio = inputRate / 16000;
  const outLen = Math.round(input.length / ratio);
  const out = new Float32Array(outLen);
  for (let i = 0; i < outLen; i++) {
    const pos = i * ratio;
    const lo = Math.floor(pos);
    const hi = Math.min(lo + 1, input.length - 1);
    const frac = pos - lo;
    out[i] = input[lo] * (1 - frac) + input[hi] * frac;
  }
  return out;
}

export function tagFrame(tag: number, body: Uint8Array): Uint8Array {
  const out = new Uint8Array(body.length + 1);
  out[0] = tag;
  out.set(body, 1);
  return out;
}

export function readTag(buf: ArrayBuffer): { tag: number; body: ArrayBuffer } {
  const bytes = new Uint8Array(buf);
  return { tag: bytes[0], body: bytes.slice(1).buffer };
}
