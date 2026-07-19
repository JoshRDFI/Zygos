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
let fakePlayback: { setEnabled: ReturnType<typeof vi.fn>; begin: ReturnType<typeof vi.fn>; enqueue: ReturnType<typeof vi.fn>; end: ReturnType<typeof vi.fn>; duck: ReturnType<typeof vi.fn>; unduck: ReturnType<typeof vi.fn>; interrupt: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> };
let fakeMicVad: { start: ReturnType<typeof vi.fn>; stop: ReturnType<typeof vi.fn> };
let vadCb: import("./micVadAdapter").MicVadCallbacks | null;

beforeEach(() => {
  localStorage.clear();
  useVoiceStore.getState().detach();
  useVoiceStore.setState({ voiceEnabled: false, micOn: false, speakerOn: false, warning: null });
  fakeMic = { start: vi.fn(() => Promise.resolve()), stop: vi.fn() };
  micFrames = null;
  fakePlayback = {
    setEnabled: vi.fn(), begin: vi.fn(), enqueue: vi.fn(), end: vi.fn(),
    duck: vi.fn(), unduck: vi.fn(), interrupt: vi.fn(), dispose: vi.fn(),
  };
  fakeMicVad = { start: vi.fn(() => Promise.resolve()), stop: vi.fn() };
  vadCb = null;
  setVoiceDeps({
    createMicAdapter: (onFrames) => { micFrames = onFrames; return fakeMic; },
    createPlayback: () => fakePlayback,
    createMicVadAdapter: (cb) => { vadCb = cb; return fakeMicVad; },
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

test("audio.unavailable reverts ALL optimistic voice state, not just the last request", () => {
  // voice_in_use denies the whole voice service for this session, so a single
  // unavailable must unwind every in-flight acquire, not only the last `pending`.
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleSpeaker();   // speaker acquire in flight
  s.toggleAlwaysOn();  // always-on acquire in flight (clobbers a single pending slot)
  expect(useVoiceStore.getState().speakerOn).toBe(true);
  expect(useVoiceStore.getState().alwaysOn).toBe(true);
  client.emit("control:audio.unavailable", { reason: "voice_in_use", message: "busy" });
  expect(useVoiceStore.getState().speakerOn).toBe(false);
  expect(useVoiceStore.getState().alwaysOn).toBe(false);
  expect(fakePlayback.setEnabled).toHaveBeenLastCalledWith(false);
  expect(fakeMicVad.stop).toHaveBeenCalled();
  expect(useVoiceStore.getState().warning).toBe("busy");
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

test("toggleAlwaysOn on starts the mic-VAD and sets alwaysOn", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  expect(useVoiceStore.getState().alwaysOn).toBe(true);
  expect(fakeMicVad.start).toHaveBeenCalled();
});

test("vad onset/speech emit audio.vad frames; speech also interrupts playback", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  vadCb!.onSpeechStart();
  for (let i = 0; i < 8; i++) vadCb!.onFrame(true); // default confirmFrames=8
  const vadStates = client.sent.filter((f) => f.type === "audio.vad").map((f) => f.payload.state);
  expect(vadStates).toContain("onset");
  expect(vadStates).toContain("speech");
  expect(fakePlayback.interrupt).toHaveBeenCalled();
});

test("onSpeechEnd streams the utterance as a bracketed STT turn + emits silence", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  vadCb!.onSpeechStart();
  vadCb!.onSpeechEnd(new Float32Array(320)); // 20ms @16k
  const types = client.sent.map((f) => f.type);
  expect(types).toContain("audio.start");
  expect(types).toContain("audio.endpoint");
  expect(types).toContain("audio.vad"); // the silence signal
  expect(client.sentBinary.some((b) => b[0] === 0x00)).toBe(true);
});

test("tts.duck / tts.unduck drive playback gain", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  client.emit("audio.out:tts.duck", { gain: 0.2 });
  client.emit("audio.out:tts.unduck", { gain: 1.0 });
  expect(fakePlayback.duck).toHaveBeenCalledWith(0.2);
  expect(fakePlayback.unduck).toHaveBeenCalled();
});

test("enabling always-on stops a running manual mic (mutual exclusion)", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleMic();
  expect(useVoiceStore.getState().micOn).toBe(true);
  s.toggleAlwaysOn();
  expect(useVoiceStore.getState().micOn).toBe(false);
  expect(useVoiceStore.getState().alwaysOn).toBe(true);
});

test("detach stops the mic-VAD and clears alwaysOn", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  useVoiceStore.getState().detach();
  expect(fakeMicVad.stop).toHaveBeenCalled();
  expect(useVoiceStore.getState().alwaysOn).toBe(false);
});

test("mic-VAD start failure reverts always-on and warns", async () => {
  fakeMicVad.start = vi.fn(() => Promise.reject(new Error("no mic")));
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  await Promise.resolve();
  await Promise.resolve();
  expect(useVoiceStore.getState().alwaysOn).toBe(false);
  expect(useVoiceStore.getState().warning).toMatch(/unavailable/i);
});

test("audio.unavailable reverts a pending always-on", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  client.emit("control:audio.unavailable", { reason: "voice_in_use", message: "busy" });
  expect(useVoiceStore.getState().alwaysOn).toBe(false);
  expect(fakeMicVad.stop).toHaveBeenCalled();
});

test("setVoiceEnabled(false) tears down always-on (stops mic-VAD, clears alwaysOn)", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  expect(useVoiceStore.getState().alwaysOn).toBe(true);
  useVoiceStore.getState().setVoiceEnabled(false);
  expect(fakeMicVad.stop).toHaveBeenCalled();
  expect(useVoiceStore.getState().alwaysOn).toBe(false);
});

test("tts.duck with empty payload ducks to the default 0.2 gain", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  client.emit("audio.out:tts.duck", {}); // no gain field
  expect(fakePlayback.duck).toHaveBeenCalledWith(0.2);
});

test("toggleMic is a no-op while always-on is active (symmetric mutual exclusion)", () => {
  const client = makeFakeClient();
  const s = useVoiceStore.getState();
  s.setVoiceEnabled(true);
  s.attach(client);
  s.toggleAlwaysOn();
  expect(useVoiceStore.getState().alwaysOn).toBe(true);
  useVoiceStore.getState().toggleMic();
  expect(useVoiceStore.getState().micOn).toBe(false);
  expect(fakeMic.start).not.toHaveBeenCalled();
});

afterEach(() => resetVoiceDeps());
