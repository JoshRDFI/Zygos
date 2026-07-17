import { create } from "zustand";
import type { Frame } from "../client/types";

export type ChatMessage = { role: "user" | "assistant"; text: string; streaming: boolean };

interface ChatState {
  messages: ChatMessage[];
  addUser: (text: string) => void;
  onFrame: (f: Frame) => void;
  reset: () => void;
}

function mapLastAssistant(
  messages: ChatMessage[],
  fn: (m: ChatMessage) => ChatMessage,
): ChatMessage[] {
  const i = messages.map((m) => m.role).lastIndexOf("assistant");
  if (i < 0) return messages;
  const copy = messages.slice();
  copy[i] = fn(copy[i]);
  return copy;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  addUser: (text) =>
    set((s) => ({ messages: [...s.messages, { role: "user", text, streaming: false }] })),
  onFrame: (f) =>
    set((s) => {
      if (f.type === "turn.start") {
        return { messages: [...s.messages, { role: "assistant", text: "", streaming: true }] };
      }
      if (f.type === "token") {
        const t = String(f.payload.text ?? "");
        return { messages: mapLastAssistant(s.messages, (m) => ({ ...m, text: m.text + t })) };
      }
      if (f.type === "turn.end") {
        const text = String(f.payload.text ?? "");
        return { messages: mapLastAssistant(s.messages, (m) => ({ ...m, text, streaming: false })) };
      }
      if (f.type === "error") {
        const text = `⚠ ${String(f.payload.message ?? "error")}`;
        return { messages: [...s.messages, { role: "assistant", text, streaming: false }] };
      }
      return s;
    }),
  reset: () => set({ messages: [] }),
}));
