export interface MicAdapter {
  start(): Promise<void>;
  stop(): void;
}

export function createMicAdapter(
  onFrames: (frames: Float32Array, rate: number) => void,
): MicAdapter {
  let ctx: AudioContext | null = null;
  let stream: MediaStream | null = null;
  let node: AudioWorkletNode | null = null;

  let stopped = false;

  const teardown = (): void => {
    node?.port.close();
    node?.disconnect();
    stream?.getTracks().forEach((t) => t.stop());
    void ctx?.close().catch(() => {});
    node = null;
    stream = null;
    ctx = null;
  };

  return {
    async start(): Promise<void> {
      stopped = false;
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (stopped) return teardown();
      ctx = new AudioContext();
      const url = new URL("./worklet/capture-processor.js", import.meta.url);
      await ctx.audioWorklet.addModule(url);
      if (stopped) return teardown();
      const source = ctx.createMediaStreamSource(stream);
      node = new AudioWorkletNode(ctx, "capture-processor", { numberOfOutputs: 0 });
      const rate = ctx.sampleRate;
      node.port.onmessage = (e: MessageEvent) => onFrames(e.data as Float32Array, rate);
      source.connect(node);
    },
    stop(): void {
      stopped = true;
      teardown();
    },
  };
}
