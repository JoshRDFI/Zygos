import { PlaybackScheduler, type AudioCtxLike } from "./playbackScheduler";

export interface PlaybackController {
  setEnabled(enabled: boolean): void;
  begin(): void;
  enqueue(body: ArrayBuffer): void;
  end(): void;
  duck(value: number): void;
  unduck(): void;
  interrupt(): void;
  dispose(): void;
}

export function createPlayback(): PlaybackController {
  let enabled = false;
  let ctx: AudioContext | null = null;
  let gain: GainNode | null = null;
  let sched: PlaybackScheduler | null = null;

  function ensure(): PlaybackScheduler {
    if (!ctx) {
      ctx = new AudioContext({ sampleRate: 24000 });
      gain = ctx.createGain();
      gain.gain.value = 1.0; // 1b holds full volume; 1c drives this on tts.duck/unduck
      gain.connect(ctx.destination);
      sched = new PlaybackScheduler(ctx as unknown as AudioCtxLike, gain);
    }
    return sched!;
  }

  function rampGain(value: number): void {
    if (ctx && gain) gain.gain.setTargetAtTime(value, ctx.currentTime, 0.015); // ~50ms, click-free
  }

  return {
    setEnabled(next: boolean): void {
      enabled = next;
      if (next) {
        ensure(); // create the AudioContext within the user gesture (Speaker toggle)
        void ctx?.resume().catch(() => {}); // autoplay policy: resume in-gesture
      }
    },
    begin(): void {
      if (enabled) { ensure().reset(); rampGain(1.0); } // fresh utterance starts at full volume
    },
    enqueue(body: ArrayBuffer): void {
      if (enabled) ensure().enqueue(body);
    },
    end(): void {
      sched?.reset();
    },
    duck(value: number): void {
      rampGain(value); // tts.duck {gain:0.2}
    },
    unduck(): void {
      rampGain(1.0); // tts.unduck {gain:1.0}
    },
    interrupt(): void {
      sched?.interrupt();
      rampGain(1.0); // stop_speech sends no unduck — restore locally
    },
    dispose(): void {
      enabled = false;
      void ctx?.close().catch(() => {});
      ctx = null;
      gain = null;
      sched = null;
    },
  };
}
