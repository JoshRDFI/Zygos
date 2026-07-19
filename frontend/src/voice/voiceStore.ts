import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Frame } from "../client/types";
import { CaptureController, type CaptureSink } from "./captureController";
import { createMicAdapter, type MicAdapter } from "./micAdapter";
import { createPlayback, type PlaybackController } from "./playbackAdapter";
import { TAG_OUT, readTag } from "./pcm";
import { VadController } from "./vadController";
import { createMicVadAdapter, type MicVadAdapter } from "./micVadAdapter";

export interface VoiceClient {
  send(f: Frame): void;
  sendBinary(b: Uint8Array): void;
  on(key: string, h: (f: Frame) => void): () => void;
  onBinary(h: (data: ArrayBuffer) => void): () => void;
}

interface VoiceDeps {
  createMicAdapter: (onFrames: (frames: Float32Array, rate: number) => void) => MicAdapter;
  createPlayback: () => PlaybackController;
  createMicVadAdapter: typeof createMicVadAdapter;
}

let deps: VoiceDeps = { createMicAdapter, createPlayback, createMicVadAdapter };
export function setVoiceDeps(d: Partial<VoiceDeps>): void {
  deps = { ...deps, ...d };
}
export function resetVoiceDeps(): void {
  deps = { createMicAdapter, createPlayback, createMicVadAdapter };
}

interface Rig {
  client: VoiceClient;
  capture: CaptureController;
  mic: MicAdapter;
  playback: PlaybackController;
  micVad: MicVadAdapter | null;
  offs: Array<() => void>;
}
let rig: Rig | null = null;

// Shared release of the mic capture + always-on VAD, so detach, setVoiceEnabled
// and handleUnavailable don't each carry their own copy of the teardown sequence.
function stopCapture(get: () => VoiceState): void {
  if (!rig) return;
  if (get().micOn) {
    rig.capture.stop();
    rig.mic.stop();
  }
  rig.micVad?.stop();
  rig.micVad = null;
}

interface VoiceState {
  voiceEnabled: boolean;
  micOn: boolean;
  speakerOn: boolean;
  alwaysOn: boolean;
  warning: string | null;
  setVoiceEnabled: (b: boolean) => void;
  toggleMic: () => void;
  toggleSpeaker: () => void;
  toggleAlwaysOn: () => void;
  attach: (client: VoiceClient) => void;
  detach: () => void;
  handleUnavailable: (payload: Record<string, unknown>) => void;
}

export const useVoiceStore = create<VoiceState>()(
  persist(
    (set, get) => ({
      voiceEnabled: false,
      micOn: false,
      speakerOn: false,
      alwaysOn: false,
      warning: null,

      attach: (client) => {
        if (rig) get().detach();
        const capture = new CaptureController({
          sendControl: (type, payload) => client.send({ channel: "control", type, payload: payload ?? {} }),
          sendBinary: (bytes) => client.sendBinary(bytes),
        } satisfies CaptureSink);
        const playback = deps.createPlayback();
        const mic = deps.createMicAdapter((frames, rate) => capture.pushFrames(frames, rate));
        const offs = [
          client.on("control:audio.unavailable", (f) => get().handleUnavailable(f.payload)),
          client.on("audio.out:tts.begin", () => playback.begin()),
          client.on("audio.out:tts.end", () => playback.end()),
          client.on("audio.out:tts.duck", (f) =>
            playback.duck(typeof f.payload.gain === "number" ? f.payload.gain : 0.2)),
          client.on("audio.out:tts.unduck", () => playback.unduck()),
          client.onBinary((data) => {
            const { tag, body } = readTag(data);
            if (tag === TAG_OUT) playback.enqueue(body);
          }),
        ];
        playback.setEnabled(get().speakerOn);
        rig = { client, capture, mic, playback, micVad: null, offs };
      },

      detach: () => {
        if (!rig) return;
        stopCapture(get);
        rig.playback.dispose();
        rig.offs.forEach((off) => off());
        rig = null;
        set({ micOn: false, speakerOn: false, alwaysOn: false });
      },

      setVoiceEnabled: (b) => {
        if (!b) {
          stopCapture(get);
          if (rig && get().speakerOn) {
            rig.playback.setEnabled(false);
            rig.client.send({ channel: "control", type: "audio.output", payload: { enabled: false } });
          }
          set({ voiceEnabled: false, micOn: false, speakerOn: false, alwaysOn: false, warning: null });
        } else {
          set({ voiceEnabled: true });
        }
      },

      toggleMic: () => {
        if (!get().voiceEnabled || !rig) return;
        // mutual exclusion: manual capture cannot run while always-on drives the
        // shared CaptureController (the VAD's onSpeechEnd would end the manual turn)
        if (get().alwaysOn) return;
        if (get().micOn) {
          rig.capture.stop();
          rig.mic.stop();
          set({ micOn: false });
          return;
        }
        set({ micOn: true, warning: null });
        rig.capture.start();
        rig.mic.start().catch(() => {
          if (rig) rig.capture.stop();
          set({ micOn: false, warning: "Microphone unavailable or permission denied." });
        });
      },

      toggleSpeaker: () => {
        if (!get().voiceEnabled || !rig) return;
        const next = !get().speakerOn;
        rig.client.send({ channel: "control", type: "audio.output", payload: { enabled: next } });
        rig.playback.setEnabled(next);
        set({ speakerOn: next, warning: next ? null : get().warning });
      },

      toggleAlwaysOn: () => {
        if (!get().voiceEnabled || !rig) return;
        if (get().alwaysOn) {
          rig.micVad?.stop();
          rig.micVad = null;
          set({ alwaysOn: false });
          return;
        }
        // mutual exclusion: a manual mic turn cannot run alongside always-on
        if (get().micOn) {
          rig.capture.stop();
          rig.mic.stop();
          set({ micOn: false });
        }
        const controller = new VadController({
          emit: (signal) => {
            if (!rig) return;
            rig.client.send({ channel: "control", type: "audio.vad", payload: { state: signal } });
            if (signal === "speech") rig.playback.interrupt();
          },
        });
        const micVad = deps.createMicVadAdapter({
          onSpeechStart: () => controller.onSpeechStart(),
          onFrame: (isSpeech) => controller.onFrame(isSpeech),
          onMisfire: () => controller.onMisfire(),
          onSpeechEnd: (audio) => {
            controller.onSpeechEnd();
            if (!rig) return;
            rig.capture.start();
            rig.capture.pushFrames(audio, 16000);
            rig.capture.stop();
          },
        });
        rig.micVad = micVad;
        set({ alwaysOn: true, warning: null });
        micVad.start().catch(() => {
          if (rig) {
            rig.micVad?.stop();
            rig.micVad = null;
          }
          set({ alwaysOn: false, warning: "Microphone or voice detector unavailable." });
        });
      },

      handleUnavailable: (payload) => {
        // voice_in_use denies this session the whole voice service, so unwind
        // every optimistically-set acquire (mic, always-on, speaker) — not just
        // the most recent one — to keep the UI in sync with the backend gate.
        const message = String(payload?.message ?? "Voice is unavailable in this session.");
        stopCapture(get);
        if (rig && get().speakerOn) {
          rig.playback.setEnabled(false);
        }
        set({ micOn: false, alwaysOn: false, speakerOn: false, warning: message });
      },
    }),
    { name: "zygos.voice", partialize: (s) => ({ voiceEnabled: s.voiceEnabled }) },
  ),
);
