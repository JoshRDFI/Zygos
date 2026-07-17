import { TAG_IN, float32ToInt16LE, resampleTo16k, tagFrame } from "./pcm";

export interface CaptureSink {
  sendControl(type: string, payload?: Record<string, unknown>): void;
  sendBinary(bytes: Uint8Array): void;
}

export class CaptureController {
  private _state: "idle" | "capturing" = "idle";
  constructor(private readonly sink: CaptureSink) {}

  get state(): "idle" | "capturing" {
    return this._state;
  }

  start(): void {
    if (this._state !== "idle") return;
    this._state = "capturing";
    this.sink.sendControl("audio.start", {});
  }

  pushFrames(frames: Float32Array, inputRate: number): void {
    if (this._state !== "capturing") return;
    const pcm = float32ToInt16LE(resampleTo16k(frames, inputRate));
    this.sink.sendBinary(tagFrame(TAG_IN, pcm));
  }

  stop(): void {
    if (this._state !== "capturing") return;
    this._state = "idle";
    this.sink.sendControl("audio.endpoint", {});
  }
}
