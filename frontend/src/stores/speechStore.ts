import { create } from "zustand";
import type { Frame } from "../client/types";

export type SpeechTimingView = {
  turnId: string;
  firstAudioMs: number | null;
  wordsAtStart: number | null;
  rateWps: number | null;
  gaps: number;
  gapMs: number;
  reason: string;
};

const CAP = 20;
const secs = (ms: number) => (ms / 1000).toFixed(1);

export function formatSpeechTiming(t: SpeechTimingView): string {
  const tail = t.reason === "complete" ? "" : ` · ${t.reason}`;
  if (t.firstAudioMs === null) return `nothing spoken${tail}`;
  const rate = t.rateWps === null ? "" : ` at ${t.rateWps} w/s`;
  const gaps =
    t.gaps === 0
      ? "no gaps"
      : `${t.gaps} ${t.gaps === 1 ? "gap" : "gaps"} (${secs(t.gapMs)} s, estimated)`;
  return `first word ${secs(t.firstAudioMs)} s · started after ${t.wordsAtStart ?? 0} words${rate} · ${gaps}${tail}`;
}

interface SpeechState {
  timings: SpeechTimingView[];
  onTrace: (f: Frame) => void;
  reset: () => void;
}

const num = (v: unknown): number | null => (v === null || v === undefined ? null : Number(v));

export const useSpeechStore = create<SpeechState>((set) => ({
  timings: [],
  onTrace: (f) => {
    const p = f.payload;
    if (p.type !== "speech.timing") return;
    const t: SpeechTimingView = {
      turnId: String(p.turn_id ?? ""),
      firstAudioMs: num(p.first_audio_ms),
      wordsAtStart: num(p.words_at_start),
      rateWps: num(p.rate_wps),
      gaps: Number(p.gaps ?? 0),
      gapMs: Number(p.gap_ms ?? 0),
      reason: String(p.reason ?? "complete"),
    };
    set((s) => ({ timings: [...s.timings, t].slice(-CAP) }));
  },
  reset: () => set({ timings: [] }),
}));
