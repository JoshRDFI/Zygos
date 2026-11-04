import { create } from "zustand";
import type { Frame } from "../client/types";

export type ThinkingEvent = {
  turnId: string;
  step: string;
  index: number;
  text: string;
  truncated: boolean;
  chars: number;
  elapsedMs: number;
};

interface ThinkState {
  enabled: boolean;
  supported: boolean;
  reason: string | null;
  voiceNotice: string | null;
  eventsByTurn: Record<string, ThinkingEvent[]>;
  turnOrder: string[];
  selectedTurnId: string | null;
  onThinkState: (f: Frame) => void;
  onVoiceCommand: (f: Frame) => void;
  onTrace: (f: Frame) => void;
  clearVoiceNotice: () => void;
  select: (turnId: string | null) => void;
  reset: () => void;
}

const initial = {
  enabled: false,
  supported: false,
  reason: null as string | null,
  voiceNotice: null as string | null,
  eventsByTurn: {} as Record<string, ThinkingEvent[]>,
  turnOrder: [] as string[],
  selectedTurnId: null as string | null,
};

export const useThinkStore = create<ThinkState>((set) => ({
  ...initial,
  onThinkState: (f) =>
    set({
      enabled: Boolean(f.payload.enabled),
      supported: Boolean(f.payload.supported),
      reason: (f.payload.reason as string | null | undefined) ?? null,
    }),
  onVoiceCommand: (f) =>
    set({ voiceNotice: `Heard “${String(f.payload.phrase ?? "")}”` }),
  onTrace: (f) => {
    const p = f.payload;
    if (p.type !== "model.thinking") return;
    const turnId = String(p.turn_id ?? "");
    const ev: ThinkingEvent = {
      turnId,
      step: String(p.step ?? ""),
      index: Number(p.index ?? 0),
      text: String(p.text ?? ""),
      truncated: Boolean(p.truncated),
      chars: Number(p.chars ?? 0),
      elapsedMs: Number(p.elapsed_ms ?? 0),
    };
    set((s) => ({
      eventsByTurn: { ...s.eventsByTurn, [turnId]: [...(s.eventsByTurn[turnId] ?? []), ev] },
      turnOrder: s.turnOrder.includes(turnId) ? s.turnOrder : [...s.turnOrder, turnId],
    }));
  },
  clearVoiceNotice: () => set({ voiceNotice: null }),
  select: (turnId) => set({ selectedTurnId: turnId }),
  reset: () => set({ ...initial }),
}));
