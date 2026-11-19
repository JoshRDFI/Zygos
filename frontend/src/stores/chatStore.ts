import { create } from "zustand";
import type { Frame, PermissionAsk, PermissionOutcome, ToolCard } from "../client/types";

// The chat-channel frame types the session subscribes to and onFrame consumes.
export const CHAT_FRAME_TYPES = ["turn.start", "token", "turn.end", "error", "partial", "final", "model.loading"] as const;

// The tools-channel frame types the session subscribes to and onFrame consumes.
export const TOOL_FRAME_TYPES = ["call", "result", "permission", "permission.result"] as const;

const DENYING: PermissionOutcome[] = ["denied", "timed_out", "cancelled"];

const rec = (v: unknown): Record<string, unknown> =>
  v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
const str = (v: unknown): string | undefined => (typeof v === "string" ? v : undefined);

function parseAsk(p: Record<string, unknown>): PermissionAsk {
  const ch = p.changed && typeof p.changed === "object" ? (p.changed as Record<string, unknown>) : null;
  return {
    argsSummary: rec(p.args_summary),
    expiresInS: typeof p.expires_in_s === "number" ? p.expires_in_s : 0,
    askedAt: Date.now(),
    canTrust: p.can_trust === true,
    server: str(p.server),
    serverTool: str(p.server_tool),
    where: p.where === "local" || p.where === "remote" ? p.where : undefined,
    address: str(p.address),
    description: str(p.description),
    claims: Array.isArray(p.claims) ? p.claims.filter((c): c is string => typeof c === "string") : [],
    ruleNote: str(p.rule_note),
    changed: ch
      ? {
          oldDescription: String(ch.old_description ?? ""), newDescription: String(ch.new_description ?? ""),
          oldSchema: ch.old_schema, newSchema: ch.new_schema,
        }
      : undefined,
  };
}

function cancelAsking(tools: ToolCard[] | undefined): ToolCard[] | undefined {
  if (!tools || !tools.some((c) => c.status === "asking")) return tools;
  return tools.map((c) => (c.status === "asking" ? { ...c, status: "denied", outcome: "cancelled" } : c));
}

/** Upsert one tool card on the last assistant message (created if there is none). */
function applyToolFrame(messages: ChatMessage[], f: Frame): ChatMessage[] {
  const p = f.payload;
  const callId = p.call_id;
  if (typeof callId !== "string" || !callId) return messages;
  if (!(TOOL_FRAME_TYPES as readonly string[]).includes(f.type)) return messages;
  const base = messages.some((m) => m.role === "assistant")
    ? messages
    : [...messages, { role: "assistant", text: "", streaming: true } as ChatMessage];
  return mapLastAssistant(base, (m) => {
    const tools = (m.tools ?? []).slice();
    let i = tools.findIndex((c) => c.callId === callId);
    if (i < 0) {
      tools.push({ callId, tool: str(p.tool) ?? "", args: {}, status: "running" });
      i = tools.length - 1;
    }
    const c: ToolCard = { ...tools[i] };
    const tool = str(p.tool);
    if (tool) c.tool = tool;
    const server = str(p.server);
    if (server) c.server = server;
    if (f.type === "call") {
      c.args = rec(p.arguments);
      if (c.status !== "asking") c.status = "running";
    } else if (f.type === "permission") {
      c.permission = parseAsk(p);
      c.status = "asking";
    } else if (f.type === "permission.result") {
      const outcome = p.outcome as PermissionOutcome;
      c.outcome = outcome;
      if (DENYING.includes(outcome)) c.status = "denied";
      // A fallback prompt's card never sees a call or result frame: it ends here.
      else c.status = callId.endsWith(":fb") ? "done" : "running";
    } else if (f.type === "result") {
      if (p.ok === true) { c.status = "done"; c.output = p.output; }
      else if (p.error_code === "tool_permission_denied") c.status = "denied";
      else { c.status = "failed"; c.errorMessage = str(p.error_message); }
    }
    tools[i] = c;
    return { ...m, tools };
  });
}

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
  /** Set from chat:model.loading until the first token or turn.end of this turn. */
  loadingModel?: string | null;
  /** The model that answered, from turn.end.model (RFC-0013 phase 2). */
  answeredBy?: string | null;
  /** Tool calls and permission prompts of this turn, in first-seen order. */
  tools?: ToolCard[];
};

interface ChatState {
  messages: ChatMessage[];
  addUser: (text: string) => void;
  addReask: (question: string) => void;
  pendingQuestion: string | null;
  onFrame: (f: Frame) => void;
  reset: () => void;
  /** Close every still-open permission card as cancelled (turn end, socket close). */
  cancelOpenPrompts: () => void;
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
      if (f.channel === "tools") {
        const messages = applyToolFrame(s.messages, f);
        return messages === s.messages ? s : { messages };
      }
      if (f.type === "turn.start") {
        let question = s.pendingQuestion ?? undefined;
        const rethinkOf = (f.payload.rethink_of as string | null | undefined) ?? null;
        if (question === undefined && rethinkOf !== null) {
          // A voice "think harder" re-asks an earlier turn: its question, not the
          // spoken phrase that is now the last user bubble.
          question = s.messages.find((m) => m.role === "assistant" && m.turnId === rethinkOf)?.question;
        }
        if (question === undefined) {
          for (let i = s.messages.length - 1; i >= 0; i--) {
            if (s.messages[i].role === "user") { question = s.messages[i].text; break; }
          }
        }
        const msg: ChatMessage = {
          role: "assistant", text: "", streaming: true,
          turnId: f.payload.turn_id as string | undefined,
          think: (f.payload.think as boolean | null | undefined) ?? null,
          rethinkOf,
          question,
        };
        return { messages: [...s.messages, msg], pendingQuestion: null };
      }
      if (f.type === "token") {
        const t = String(f.payload.text ?? "");
        return { messages: mapLastAssistant(s.messages, (m) => ({ ...m, text: m.text + t, loadingModel: null })) };
      }
      if (f.type === "model.loading") {
        const tid = f.payload.turn_id as string | undefined;
        const label = String(f.payload.model ?? "");
        const i = s.messages.map((m) => m.role === "assistant" && m.streaming && m.turnId === tid).lastIndexOf(true);
        if (i < 0 || !label) return s;
        return { messages: s.messages.map((m, j) => (j === i ? { ...m, loadingModel: label } : m)) };
      }
      if (f.type === "turn.end") {
        const text = String(f.payload.text ?? "");
        const thinkingMs = (f.payload.thinking_ms as number | null | undefined) ?? null;
        const reason = (f.payload.think_unsupported_reason as string | null | undefined) ?? null;
        const model = f.payload.model as { model?: unknown } | null | undefined;
        const answeredBy = model && typeof model.model === "string" ? model.model : null;
        return {
          messages: mapLastAssistant(s.messages, (m) => ({
            ...m, text, streaming: false, thinkingMs, thinkUnsupportedReason: reason,
            loadingModel: null, answeredBy, tools: cancelAsking(m.tools),
          })),
        };
      }
      if (f.type === "error") {
        const text = `⚠ ${String(f.payload.message ?? "error")}`;
        // A failed turn sends no turn.end: release its stuck streaming message, or
        // "Thinking…" never clears and every "Think it through" stays disabled.
        const i = s.messages.map((m) => m.role === "assistant" && m.streaming).lastIndexOf(true);
        const released = i < 0 ? s.messages : s.messages.map((m, j) => (j === i ? { ...m, streaming: false, loadingModel: null } : m));
        return { messages: [...released, { role: "assistant", text, streaming: false }] };
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
  cancelOpenPrompts: () =>
    set((s) => ({
      messages: s.messages.map((m) => (m.tools?.some((c) => c.status === "asking") ? { ...m, tools: cancelAsking(m.tools) } : m)),
    })),
}));
