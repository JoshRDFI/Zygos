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
let pending: "mic" | "speaker" | "alwayson" | null = null;

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
        if (get().micOn) {
          rig.capture.stop();
          rig.mic.stop();
        }
        rig.micVad?.stop();
        rig.playback.dispose();
        rig.offs.forEach((off) => off());
        rig = null;
        pending = null;
        set({ micOn: false, speakerOn: false, alwaysOn: false });
      },

      setVoiceEnabled: (b) => {
        if (!b) {
          if (rig && get().micOn) {
            rig.capture.stop();
            rig.mic.stop();
          }
          if (rig && get().alwaysOn) {
            rig.micVad?.stop();
            rig.micVad = null;
          }
          if (rig && get().speakerOn) {
            rig.playback.setEnabled(false);
            rig.client.send({ channel: "control", type: "audio.output", payload: { enabled: false } });
          }
          pending = null;
          set({ voiceEnabled: false, micOn: false, speakerOn: false, alwaysOn: false, warning: null });
        } else {
          set({ voiceEnabled: true });
        }
      },

      toggleMic: () => {
        if (!get().voiceEnabled || !rig) return;
        if (get().micOn) {
          rig.capture.stop();
          rig.mic.stop();
          pending = null;
          set({ micOn: false });
          return;
        }
        pending = "mic";
        set({ micOn: true, warning: null });
        rig.capture.start();
        rig.mic.start().catch(() => {
          if (rig) rig.capture.stop();
          pending = null;
          set({ micOn: false, warning: "Microphone unavailable or permission denied." });
        });
      },

      toggleSpeaker: () => {
        if (!get().voiceEnabled || !rig) return;
        const next = !get().speakerOn;
        pending = next ? "speaker" : null;
        rig.client.send({ channel: "control", type: "audio.output", payload: { enabled: next } });
        rig.playback.setEnabled(next);
        set({ speakerOn: next, warning: next ? null : get().warning });
      },

      toggleAlwaysOn: () => {
        if (!get().voiceEnabled || !rig) return;
        if (get().alwaysOn) {
          rig.micVad?.stop();
          rig.micVad = null;
          pending = null;
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
        pending = "alwayson";
        set({ alwaysOn: true, warning: null });
        micVad.start().catch(() => {
          if (rig) {
            rig.micVad?.stop();
            rig.micVad = null;
          }
          pending = null;
          set({ alwaysOn: false, warning: "Microphone or voice detector unavailable." });
        });
      },

      handleUnavailable: (payload) => {
        const message = String(payload?.message ?? "Voice is unavailable in this session.");
        if (pending === "mic" && rig) {
          rig.capture.stop();
          rig.mic.stop();
          set({ micOn: false });
        } else if (pending === "speaker" && rig) {
          rig.playback.setEnabled(false);
          set({ speakerOn: false });
        } else if (pending === "alwayson" && rig) {
          rig.micVad?.stop();
          rig.micVad = null;
          set({ alwaysOn: false });
        }
        pending = null;
        set({ warning: message });
      },
    }),
    { name: "zygos.voice", partialize: (s) => ({ voiceEnabled: s.voiceEnabled }) },
  ),
);
