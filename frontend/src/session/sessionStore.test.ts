import { afterEach, beforeEach, expect, test, vi } from "vitest";
import {
  useSessionStore, setSessionDeps, resetSessionDeps, getSessionClient,
} from "./sessionStore";
import { useChatStore } from "../stores/chatStore";
import { useVoiceStore } from "../voice/voiceStore";

function makeFakeClient() {
  const handlers = new Map<string, (f: import("../client/types").Frame) => void>();
  const openCbs: Array<() => void> = [];
  const closeCbs: Array<() => void> = [];
  return {
    send: vi.fn(),
    sendBinary: vi.fn(),
    connect: vi.fn(),
    close: vi.fn(),
    on(key: string, h: (f: import("../client/types").Frame) => void) { handlers.set(key, h); return () => handlers.delete(key); },
    onBinary() { return () => {}; },
    onOpen(cb: () => void) { openCbs.push(cb); return () => {}; },
    onClose(cb: () => void) { closeCbs.push(cb); return () => {}; },
    emit(key: string, payload: Record<string, unknown>) {
      const [channel, type] = key.split(/:(.*)/s);
      handlers.get(key)?.({ channel, type, payload });
    },
    fireOpen() { openCbs.forEach((c) => c()); },
    fireClose() { closeCbs.forEach((c) => c()); },
  };
}

let fake: ReturnType<typeof makeFakeClient>;
let createSession: ReturnType<typeof vi.fn>;

beforeEach(() => {
  useSessionStore.getState().stop(); // clear the module rig between tests
  useChatStore.getState().reset();
  fake = makeFakeClient();
  createSession = vi.fn(() => Promise.resolve("sess-1"));
  setSessionDeps({
    createSession,
    createClient: () => fake as unknown as import("../client/wsClient").WsClient,
  });
});
afterEach(() => { resetSessionDeps(); vi.restoreAllMocks(); });

test("start() creates one session, connects, and records the id", async () => {
  useSessionStore.getState().start();
  expect(useSessionStore.getState().status).toBe("connecting");
  await Promise.resolve();
  await Promise.resolve();
  expect(createSession).toHaveBeenCalledTimes(1);
  expect(fake.connect).toHaveBeenCalledTimes(1);
  expect(useSessionStore.getState().sessionId).toBe("sess-1");
  expect(getSessionClient()).toBe(fake);
});

test("start() is idempotent — two synchronous calls create one session", async () => {
  useSessionStore.getState().start();
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  expect(createSession).toHaveBeenCalledTimes(1);
});

test("status transitions connected on open and disconnected on close", async () => {
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  expect(useSessionStore.getState().status).toBe("connecting"); // socket not open yet
  fake.fireOpen();
  expect(useSessionStore.getState().status).toBe("connected");
  fake.fireClose();
  expect(useSessionStore.getState().status).toBe("disconnected");
});

test("createSession rejection sets error and is retryable", async () => {
  createSession.mockImplementationOnce(() => Promise.reject(new Error("boom")));
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  expect(useSessionStore.getState().status).toBe("error");
  // retry: the guard is cleared, so a second start() calls createSession again
  useSessionStore.getState().start();
  await Promise.resolve();
  expect(createSession).toHaveBeenCalledTimes(2);
});

test("chat frames route to chatStore via the registered handlers", async () => {
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  fake.emit("chat:turn.start", {});
  const msgs = useChatStore.getState().messages;
  expect(msgs).toHaveLength(1);
  expect(msgs[0].role).toBe("assistant");
});

test("start() attaches voice exactly once", async () => {
  const attach = vi.spyOn(useVoiceStore.getState(), "attach");
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  expect(attach).toHaveBeenCalledTimes(1);
  expect(attach).toHaveBeenCalledWith(fake);
});

test("getSessionClient() is null before start; stop() tears down", async () => {
  useSessionStore.getState().stop();
  expect(getSessionClient()).toBeNull();
  useSessionStore.getState().start();
  await Promise.resolve();
  await Promise.resolve();
  expect(getSessionClient()).toBe(fake);
  useSessionStore.getState().stop();
  expect(getSessionClient()).toBeNull();
  expect(fake.close).toHaveBeenCalled();
  expect(useSessionStore.getState().status).toBe("idle");
});
