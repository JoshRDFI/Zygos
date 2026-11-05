import { create } from "zustand";
import type { Frame } from "../client/types";

export type ModelTraceLine =
  | { kind: "chosen"; turnId: string; category: string; provider: string; model: string; reason: string }
  | { kind: "loaded"; provider: string; model: string; loadMs: number; evicted: string[] }
  | { kind: "skipped"; provider: string; model: string; reason: string };

const CAP = 50;

export function formatModelTrace(l: ModelTraceLine): string {
  if (l.kind === "chosen") return `${l.category}: ${l.provider}/${l.model} — ${l.reason}`;
  if (l.kind === "loaded") {
    const evicted = l.evicted.length > 0 ? ` — evicted ${l.evicted.join(", ")}` : "";
    return `loaded ${l.provider}/${l.model} in ${l.loadMs} ms${evicted}`;
  }
  return `skipped ${l.provider}/${l.model}: ${l.reason}`;
}

interface ModelTraceState {
  lines: ModelTraceLine[];
  onTrace: (f: Frame) => void;
  reset: () => void;
}

export const useModelTraceStore = create<ModelTraceState>((set) => ({
  lines: [],
  onTrace: (f) => {
    const p = f.payload;
    const provider = String(p.provider ?? "");
    const model = String(p.model ?? "");
    let line: ModelTraceLine;
    if (p.type === "model.chosen") {
      line = {
        kind: "chosen", turnId: String(p.turn_id ?? ""), category: String(p.category ?? ""),
        provider, model, reason: String(p.reason ?? ""),
      };
    } else if (p.type === "model.loaded") {
      line = {
        kind: "loaded", provider, model, loadMs: Number(p.load_ms ?? 0),
        evicted: Array.isArray(p.evicted) ? p.evicted.map(String) : [],
      };
    } else if (p.type === "route.skipped") {
      line = { kind: "skipped", provider, model, reason: String(p.reason ?? "") };
    } else return;
    set((s) => ({ lines: [...s.lines, line].slice(-CAP) }));
  },
  reset: () => set({ lines: [] }),
}));
