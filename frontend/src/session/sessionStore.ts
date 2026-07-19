import { create } from "zustand";
import { createSession as restCreateSession } from "../client/rest";
import { WsClient } from "../client/wsClient";
import { CHAT_FRAME_TYPES, useChatStore } from "../stores/chatStore";
import { useVoiceStore } from "../voice/voiceStore";

export type SessionStatus = "idle" | "connecting" | "connected" | "disconnected" | "error";

interface SessionRig {
  client: WsClient;
  offs: Array<() => void>;
}
let rig: SessionRig | null = null;
let startPromise: Promise<void> | null = null;
let epoch = 0;

interface SessionDeps {
  createSession: () => Promise<string>;
  createClient: (id: string) => WsClient;
}
const defaultDeps: SessionDeps = {
  createSession: restCreateSession,
  createClient: (id) => new WsClient(id),
};
let deps: SessionDeps = { ...defaultDeps };
export function setSessionDeps(d: Partial<SessionDeps>): void {
  deps = { ...deps, ...d };
}
export function resetSessionDeps(): void {
  deps = { ...defaultDeps };
}

export function getSessionClient(): WsClient | null {
  return rig?.client ?? null;
}

interface SessionState {
  sessionId: string | null;
  status: SessionStatus;
  start: () => void;
  stop: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessionId: null,
  status: "idle",

  start: () => {
    if (rig || startPromise) return; // already started or starting (StrictMode-safe)
    const myEpoch = epoch;
    set({ status: "connecting" });
    startPromise = deps
      .createSession()
      .then((id) => {
        if (myEpoch !== epoch) return; // stop() ran while this start was in-flight; abandon it
        const client = deps.createClient(id);
        const onFrame = useChatStore.getState().onFrame;
        const offs = CHAT_FRAME_TYPES.map((t) => client.on(`chat:${t}`, onFrame));
        offs.push(client.onOpen(() => set({ status: "connected" })));
        offs.push(client.onClose(() => set({ status: "disconnected" })));
        useVoiceStore.getState().attach(client);
        client.connect();
        rig = { client, offs };
        startPromise = null;
        set({ sessionId: id });
      })
      .catch((err) => {
        if (myEpoch !== epoch) return; // stop() ran while this start was in-flight; abandon it
        console.error("session start failed", err);
        startPromise = null; // allow a retry
        set({ status: "error" });
      });
  },

  stop: () => {
    epoch += 1; // invalidate any in-flight start() so its .then()/.catch() abandons
    useVoiceStore.getState().detach();
    rig?.client.close();
    rig?.offs.forEach((off) => off());
    rig = null;
    startPromise = null;
    set({ sessionId: null, status: "idle" });
  },
}));
