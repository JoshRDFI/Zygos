import { create } from "zustand";
import type { Frame } from "../client/types";
import { useThinkStore } from "./thinkStore";

// The chat-channel frame types the session subscribes to and onFrame consumes.
export const CHAT_FRAME_TYPES = ["turn.start", "token", "turn.end", "error", "partial", "final", "voice_command"] as const;

export type ChatMessage = {
  role: "user" | "assistant";
  text: string;
  streaming: boolean;
  turnId?: string;
  think?: boolean | null;
  rethinkOf?: string | null;
  question?: string;
  thinkingMs?: number | null;
  thinkUnsupportedReason?: string | null;
};

interface ChatState {
  messages: ChatMessage[];
  addUser: (text: string) => void;
  addReask: (question: string) => void;
  pendingQuestion: string | null;
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
  pendingQuestion: null,
  addUser: (text) =>
    set((s) => ({ messages: [...s.messages, { role: "user", text, streaming: false }], pendingQuestion: null })),
  addReask: (question) => set({ pendingQuestion: question }),
  onFrame: (f) =>
    set((s) => {
      if (f.type === "turn.start") {
        let question = s.pendingQuestion ?? undefined;
        if (question === undefined) {
          for (let i = s.messages.length - 1; i >= 0; i--) {
            if (s.messages[i].role === "user") { question = s.messages[i].text; break; }
          }
        }
        const msg: ChatMessage = {
          role: "assistant", text: "", streaming: true,
          turnId: f.payload.turn_id as string | undefined,
          think: (f.payload.think as boolean | null | undefined) ?? null,
          rethinkOf: (f.payload.rethink_of as string | null | undefined) ?? null,
          question,
        };
        return { messages: [...s.messages, msg], pendingQuestion: null };
      }
      if (f.type === "token") {
        const t = String(f.payload.text ?? "");
        return { messages: mapLastAssistant(s.messages, (m) => ({ ...m, text: m.text + t })) };
      }
      if (f.type === "turn.end") {
        const text = String(f.payload.text ?? "");
        useThinkStore.getState().clearVoiceNotice();
        const thinkingMs = (f.payload.thinking_ms as number | null | undefined) ?? null;
        const reason = (f.payload.think_unsupported_reason as string | null | undefined) ?? null;
        return {
          messages: mapLastAssistant(s.messages, (m) => ({
            ...m, text, streaming: false, thinkingMs, thinkUnsupportedReason: reason,
          })),
        };
      }
      if (f.type === "error") {
        const text = `⚠ ${String(f.payload.message ?? "error")}`;
        return { messages: [...s.messages, { role: "assistant", text, streaming: false }] };
      }
      if (f.type === "final") {
        const text = String(f.payload.text ?? "");
        if (!text) return s;
        return { messages: [...s.messages, { role: "user", text, streaming: false }] };
      }
      // "partial" frames (interim STT) are ignored this increment — faster-whisper
      // is final-only; a future streaming engine would render them here.
      return s;
    }),
  reset: () => set({ messages: [], pendingQuestion: null }),
}));
