import { expect, test, vi } from "vitest";
import { WsClient, frameKey, parseFrame } from "./wsClient";
import type { Frame } from "./types";

test("frameKey and parseFrame", () => {
  expect(frameKey({ channel: "chat", type: "token", payload: {} })).toBe("chat:token");
  expect(parseFrame('{"channel":"chat","type":"token","payload":{"text":"hi"}}'))
    .toEqual({ channel: "chat", type: "token", payload: { text: "hi" } });
  expect(parseFrame("not json")).toBeNull();
  expect(parseFrame("[1,2,3]")).toBeNull();
});

class FakeSocket {
  readyState = 1;
  sent: string[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  send(d: string) { this.sent.push(d); }
  close() { this.readyState = 3; }
  emit(frame: Frame) { this.onmessage?.({ data: JSON.stringify(frame) }); }
}

test("dispatches inbound frames to matching subscribers only", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  client.socketFactory = () => fake;
  client.connect();

  const tokens: string[] = [];
  client.on("chat:token", (f) => tokens.push(String(f.payload.text)));
  const ends = vi.fn();
  client.on("chat:turn.end", ends);

  fake.emit({ channel: "chat", type: "token", payload: { text: "he" } });
  fake.emit({ channel: "chat", type: "token", payload: { text: "llo" } });
  fake.emit({ channel: "trace", type: "event", payload: {} });

  expect(tokens).toEqual(["he", "llo"]);
  expect(ends).not.toHaveBeenCalled();
});

test("send encodes frames; unsubscribe stops delivery", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  client.socketFactory = () => fake;
  client.connect();
  client.send({ channel: "chat", type: "user_message", payload: { text: "hi" } });
  expect(JSON.parse(fake.sent[0])).toEqual({ channel: "chat", type: "user_message", payload: { text: "hi" } });

  const seen = vi.fn();
  const off = client.on("chat:token", seen);
  off();
  fake.emit({ channel: "chat", type: "token", payload: { text: "x" } });
  expect(seen).not.toHaveBeenCalled();
});
