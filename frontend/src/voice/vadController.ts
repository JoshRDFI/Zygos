export type VadSignal = "onset" | "speech" | "silence";

export interface VadControllerDeps {
  emit(signal: VadSignal): void;
  confirmFrames?: number;
}

const DEFAULT_CONFIRM_FRAMES = 8; // ~256ms at 32ms/frame (Silero v5)

/**
 * Two-stage barge-in staging on top of MicVAD's callbacks:
 *   onSpeechStart -> "onset" (tentative; backend ducks)
 *   confirmFrames consecutive speech frames -> "speech" once (backend stops the turn)
 *   onSpeechEnd / onMisfire -> "silence" (backend unducks; false-alarm self-heals)
 * Pure: a deterministic function of the callback sequence. No timers, no Web Audio.
 */
export class VadController {
  private active = false;   // between onSpeechStart and end/misfire
  private confirmed = false;
  private speechFrames = 0;
  private readonly confirmFrames: number;

  constructor(private readonly deps: VadControllerDeps) {
    this.confirmFrames = deps.confirmFrames ?? DEFAULT_CONFIRM_FRAMES;
  }

  onSpeechStart(): void {
    this.active = true;
    this.confirmed = false;
    this.speechFrames = 0;
    this.deps.emit("onset");
  }

  onFrame(isSpeech: boolean): void {
    if (!this.active || this.confirmed) return;
    if (!isSpeech) {
      this.speechFrames = 0; // require CONSECUTIVE speech frames
      return;
    }
    this.speechFrames += 1;
    if (this.speechFrames >= this.confirmFrames) {
      this.confirmed = true;
      this.deps.emit("speech");
    }
  }

  onSpeechEnd(): void {
    if (!this.active) return;
    this.active = false;
    this.deps.emit("silence");
  }

  onMisfire(): void {
    if (!this.active) return;
    this.active = false;
    this.deps.emit("silence");
  }
}
