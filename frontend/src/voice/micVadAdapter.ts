export interface MicVadCallbacks {
  onSpeechStart(): void;
  onFrame(isSpeech: boolean): void; // true when this frame's speech probability crosses threshold
  onSpeechEnd(audio16k: Float32Array): void; // complete utterance, 16kHz, incl. pre/post padding
  onMisfire(): void; // speech shorter than minSpeechFrames -> discard
}

export interface MicVadAdapter {
  start(): Promise<void>;
  stop(): void;
}

const ASSET_PATH = "/vad/"; // self-hosted (see scripts/vendor-vad-assets.mjs)
const POSITIVE_THRESHOLD = 0.5; // MicVAD default; also our onFrame boolean cut

/**
 * Thin lazy shell around @ricky0123/vad-web MicVAD. Owns getUserMedia + Silero +
 * its worklet; surfaces MicVAD's callbacks. Not unit-tested (needs real Web Audio/WASM);
 * the `stopped` guard mirrors micAdapter's stop-before-start race handling.
 *
 * Note vs. the naive shape: MicVAD.new(...)'s `start`/`destroy` are async
 * (`() => Promise<void>`), and `onFrameProcessed` is called with
 * `(probabilities: { isSpeech, notSpeech }, frame: Float32Array)` - we only need
 * `probabilities.isSpeech`, so the extra `frame` arg is simply not declared here.
 */
export function createMicVadAdapter(cb: MicVadCallbacks): MicVadAdapter {
  let vad: { start(): Promise<void>; destroy(): Promise<void> } | null = null;
  let stopped = false;

  return {
    async start(): Promise<void> {
      stopped = false;
      const { MicVAD } = await import("@ricky0123/vad-web");
      if (stopped) return;
      const instance = await MicVAD.new({
        model: "v5",
        baseAssetPath: ASSET_PATH,
        onnxWASMBasePath: ASSET_PATH,
        onSpeechStart: () => cb.onSpeechStart(),
        onFrameProcessed: (probs: { isSpeech: number }) =>
          cb.onFrame(probs.isSpeech >= POSITIVE_THRESHOLD),
        onSpeechEnd: (audio: Float32Array) => cb.onSpeechEnd(audio),
        onVADMisfire: () => cb.onMisfire(),
      });
      if (stopped) {
        await instance.destroy();
        return;
      }
      vad = instance;
      await vad.start();
    },
    stop(): void {
      stopped = true;
      void vad?.destroy();
      vad = null;
    },
  };
}
