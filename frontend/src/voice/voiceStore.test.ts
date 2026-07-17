import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { useVoiceStore, setVoiceDeps, resetVoiceDeps, type VoiceClient } from "./voiceStore";
import { TAG_OUT, tagFrame } from "./pcm";

function makeFakeClient() {
  const handlers = new Map<string, (f: import("../client/types").Frame) => void>();
  let bin: ((d: ArrayBuffer) => void) | null = null;
  return {
    sent: [] as import("../client/types").Frame[],
    sentBinary: [] as Uint8Array[],
    send(this: { sent: import("../client/types").Frame[] }, f) { this.sent.push(f); },
    sendBinary(this: { sentBinary: Uint8Array[] }, b) { this.sentBinary.push(b); },
    on(key, h) { handlers.set(key, h); return () => handlers.delete(key); },
    onBinary(h) { bin = h; return () => { bin = null; }; },
    emit(key: string, payload: Record<string, unknown>) {
      const [channel, type] = key.split(/:(.*)/s);
      handlers.get(key)?.({ channel, type, payload });
    },
    emitBinary(d: ArrayBuffer) { bin?.(d); },
  } satisfies VoiceClient & Record<string, unknown>;
}

let fakeMic: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
let micFrames: ((f: Float32Array, r: number) => void) | null;
let fakePlayback: { setEnabled: ReturnType<typeof vi.fn>; begin: ReturnType<typeof vi.fn>; enqueue: ReturnType<typeof vi.fn>; end: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> };

beforeEach(() => {
  localStorage.clear();
  useVoiceStore.getState().detach();
  useVoiceStore.setState({ voiceEnabled: false, micOn: false, speakerOn: false, warning: null });
  fakeMic = { start: vi.fn(() => Promise.resolve()), stop: vi.fn() };
  micFrames = null;
  fakePlayback = { setEnabled: vi.fn(), begin: vi.fn(), enqueue: vi.fn(), end: vi.fn(), dispose: vi.fn() };
  setVoiceDeps({
    createMicAdapter: (onFrames) => { micFrames = onFrames; return fakeMic; },
    createPlayback: () => fakePlayback,
  });
});

test("toggleMic on emits audio.start + starts mic; off emits audio.endpoint", async () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleMic();
  await Promise.resolve();
  expect(useVoiceStore.getState().micOn).toBe(true);
  expect(client.sent[0]).toEqual({ channel: "control", type: "audio.start", payload: {} });
  expect(fakeMic.start).toHaveBeenCalled();
  useVoiceStore.getState().toggleMic();
  expect(client.sent.at(-1)).toEqual({ channel: "control", type: "audio.endpoint", payload: {} });
  expect(fakeMic.stop).toHaveBeenCalled();
  expect(useVoiceStore.getState().micOn).toBe(false);
});

test("captured frames flow to the client as tagged binary", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleMic();
  micFrames!(new Float32Array(32), 16000);
  expect(client.sentBinary).toHaveLength(1);
  expect(client.sentBinary[0][0]).toBe(0x00);
});

test("getUserMedia denial reverts Mic and sets a warning", async () => {
  fakeMic.start = vi.fn(() => Promise.reject(new Error("denied")));
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleMic();
  await Promise.resolve();
  await Promise.resolve();
  expect(useVoiceStore.getState().micOn).toBe(false);
  expect(useVoiceStore.getState().warning).toMatch(/microphone/i);
});

test("toggleSpeaker emits audio.output and enables playback", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleSpeaker();
  expect(client.sent.at(-1)).toEqual({ channel: "control", type: "audio.output", payload: { enabled: true } });
  expect(fakePlayback.setEnabled).toHaveBeenLastCalledWith(true);
});

test("detach resets speakerOn and disposes playback (no silent-speaker desync on re-attach)", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleSpeaker();
  expect(useVoiceStore.getState().speakerOn).toBe(true);
  useVoiceStore.getState().detach();
  expect(useVoiceStore.getState().speakerOn).toBe(false);
  expect(fakePlayback.dispose).toHaveBeenCalled();
  // re-attach a new session: speakerOn is now false, so attach() will not
  // locally re-enable playback without a fresh audio.output frame.
  const client2 = makeFakeClient();
  useVoiceStore.getState().attach(client2);
  expect(useVoiceStore.getState().speakerOn).toBe(false);
});

test("audio.unavailable reverts the pending toggle and warns", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleMic();
  client.emit("control:audio.unavailable", { reason: "voice_in_use", message: "Voice is active elsewhere." });
  expect(useVoiceStore.getState().micOn).toBe(false);
  expect(useVoiceStore.getState().warning).toBe("Voice is active elsewhere.");
});

test("inbound 0x01 binary routes to playback.enqueue", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.speakerOn = false;
  s.attach(client);
  client.emitBinary(tagFrame(TAG_OUT, new Uint8Array([1, 2, 3, 4])).buffer as ArrayBuffer);
  expect(fakePlayback.enqueue).toHaveBeenCalledTimes(1);
  expect(new Uint8Array(fakePlayback.enqueue.mock.calls[0][0])).toEqual(new Uint8Array([1, 2, 3, 4]));
});

test("tts.begin/end drive the playback controller", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  client.emit("audio.out:tts.begin", { turn_id: "t1" });
  client.emit("audio.out:tts.end", { turn_id: "t1", reason: "complete" });
  expect(fakePlayback.begin).toHaveBeenCalled();
  expect(fakePlayback.end).toHaveBeenCalled();
});

test("setVoiceEnabled(false) disables mic and speaker", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleSpeaker();
  s.setVoiceEnabled(false);
  const st = useVoiceStore.getState();
  expect(st.voiceEnabled).toBe(false);
  expect(st.speakerOn).toBe(false);
  expect(st.micOn).toBe(false);
});

test("voiceEnabled persists to localStorage['zygos.voice']", () => {
  useVoiceStore.getState().setVoiceEnabled(true);
  expect(localStorage.getItem("zygos.voice")).toMatch(/"voiceEnabled":true/);
});

afterEach(() => resetVoiceDeps());
