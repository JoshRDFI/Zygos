import { int16ToFloat32 } from "./pcm";

export interface AudioBufferLike {
  getChannelData(ch: number): Float32Array;
}
export interface BufferSourceLike {
  buffer: AudioBufferLike | null;
  connect(target: unknown): void;
  start(when: number): void;
}
export interface AudioCtxLike {
  readonly sampleRate: number;
  readonly currentTime: number;
  createBuffer(channels: number, length: number, rate: number): AudioBufferLike;
  createBufferSource(): BufferSourceLike;
}

const RATE = 24000;

export class PlaybackScheduler {
  private cursor = 0;
  constructor(private readonly ctx: AudioCtxLike, private readonly target: unknown) {}

  enqueue(int16: ArrayBuffer): void {
    const samples = int16ToFloat32(int16);
    if (samples.length === 0) return;
    const buffer = this.ctx.createBuffer(1, samples.length, RATE);
    buffer.getChannelData(0).set(samples);
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.target);
    const startAt = Math.max(this.ctx.currentTime, this.cursor);
    src.start(startAt);
    this.cursor = startAt + samples.length / RATE;
  }

  reset(): void {
    this.cursor = 0;
  }
}
