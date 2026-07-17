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

  return {
    async start(): Promise<void> {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      ctx = new AudioContext();
      const url = new URL("./worklet/capture-processor.js", import.meta.url);
      await ctx.audioWorklet.addModule(url);
      const source = ctx.createMediaStreamSource(stream);
      node = new AudioWorkletNode(ctx, "capture-processor", { numberOfOutputs: 0 });
      const rate = ctx.sampleRate;
      node.port.onmessage = (e: MessageEvent) => onFrames(e.data as Float32Array, rate);
      source.connect(node);
      // Do NOT connect node to destination — we only tap samples, not monitor.
    },
    stop(): void {
      node?.port.close();
      node?.disconnect();
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close().catch(() => {});
      node = null;
      stream = null;
      ctx = null;
    },
  };
}
