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
  binaryType = "";
  sent: string[] = [];
  onmessage: ((e: { data: string | ArrayBuffer }) => void) | null = null;
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

test("sendBinary sends bytes only when open; onBinary receives ArrayBuffer messages", () => {
  class BinSocket {
    readyState = 1;
    binaryType = "";
    sent: unknown[] = [];
    onmessage: ((e: { data: string | ArrayBuffer }) => void) | null = null;
    onopen: (() => void) | null = null;
    send(d: unknown) { this.sent.push(d); }
    close() { this.readyState = 3; }
  }
  const client = new WsClient("sess-1");
  const sock = new BinSocket();
  client.socketFactory = () => sock as unknown as import("./wsClient").WebSocketLike;
  client.connect();
  expect(sock.binaryType).toBe("arraybuffer");

  const bytes = new Uint8Array([0, 1, 2]);
  client.sendBinary(bytes);
  expect(sock.sent[0]).toBe(bytes);

  const got: ArrayBuffer[] = [];
  const off = client.onBinary((d) => got.push(d));
  const buf = new Uint8Array([1, 9, 9]).buffer;
  sock.onmessage!({ data: buf });
  expect(got).toHaveLength(1);
  expect(new Uint8Array(got[0])[0]).toBe(1);

  off();
  sock.onmessage!({ data: new Uint8Array([2]).buffer });
  expect(got).toHaveLength(1);

  sock.readyState = 3;
  client.sendBinary(new Uint8Array([5]));
  expect(sock.sent).toHaveLength(1); // no-op when not open
});

test("text frames still dispatch after binary support added", () => {
  const client = new WsClient("sess-1");
  const sock = {
    readyState: 1, binaryType: "", onopen: null,
    onmessage: null as ((e: { data: string | ArrayBuffer }) => void) | null,
    send() {}, close() {},
  };
  client.socketFactory = () => sock as unknown as import("./wsClient").WebSocketLike;
  client.connect();
  const seen: string[] = [];
  client.on("chat:token", (f) => seen.push(String(f.payload.text)));
  sock.onmessage!({ data: JSON.stringify({ channel: "chat", type: "token", payload: { text: "x" } }) });
  expect(seen).toEqual(["x"]);
});
