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
  sent: Array<string | ArrayBufferView> = [];
  onmessage: ((e: { data: string | ArrayBuffer }) => void) | null = null;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  send(d: string | ArrayBufferView) { this.sent.push(d); }
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
  expect(JSON.parse(fake.sent[0] as string)).toEqual({ channel: "chat", type: "user_message", payload: { text: "hi" } });

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

test("frames sent while CONNECTING are queued and flushed in order on open", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  fake.readyState = 0; // CONNECTING — socket not open yet
  client.socketFactory = () => fake;
  client.connect();

  client.send({ channel: "chat", type: "user_message", payload: { text: "first" } });
  client.sendBinary(new Uint8Array([9]));
  client.send({ channel: "chat", type: "user_message", payload: { text: "second" } });
  expect(fake.sent).toHaveLength(0); // nothing sent while connecting

  fake.readyState = 1;
  fake.onopen!(); // socket opens -> flush buffered sends in order
  expect(fake.sent).toHaveLength(3);
  expect(JSON.parse(fake.sent[0] as string).payload.text).toBe("first");
  expect(fake.sent[1]).toEqual(new Uint8Array([9]));
  expect(JSON.parse(fake.sent[2] as string).payload.text).toBe("second");
});

test("connect() clears frames buffered against a previous never-opened socket", () => {
  const dead = new FakeSocket(); dead.readyState = 0;
  const fresh = new FakeSocket(); fresh.readyState = 0;
  const sockets = [dead, fresh];
  let i = 0;
  const client = new WsClient("sess-1");
  client.socketFactory = () => sockets[i++];

  client.connect(); // dead socket, stuck CONNECTING
  client.send({ channel: "chat", type: "user_message", payload: { text: "stale" } });
  client.connect(); // reconnect on a fresh socket — the stale queue must not carry over

  fresh.readyState = 1;
  fresh.onopen!();
  expect(fresh.sent).toHaveLength(0);
});

test("preOpenQueue is bounded while the socket stays CONNECTING", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket(); fake.readyState = 0;
  client.socketFactory = () => fake;
  client.connect();

  for (let n = 0; n < 5000; n++) client.sendBinary(new Uint8Array([n & 0xff]));
  fake.readyState = 1;
  fake.onopen!();
  expect(fake.sent.length).toBeLessThanOrEqual(4096); // capped, not unbounded
});

test("frames sent after the socket is closed are dropped, not queued", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  fake.readyState = 3; // CLOSED
  client.socketFactory = () => fake;
  client.connect();
  client.send({ channel: "chat", type: "user_message", payload: { text: "gone" } });
  fake.readyState = 1;
  fake.onopen?.();
  expect(fake.sent).toHaveLength(0);
});

test("onOpen fires on socket open and still flushes the pre-open queue", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  fake.readyState = 0; // CONNECTING
  client.socketFactory = () => fake;
  client.connect();

  const opened = vi.fn();
  client.onOpen(opened);
  client.send({ channel: "chat", type: "user_message", payload: { text: "buffered" } });

  fake.readyState = 1;
  fake.onopen!(); // open -> flush + notify
  expect(opened).toHaveBeenCalledTimes(1);
  expect(fake.sent).toHaveLength(1); // queued frame flushed
});

test("onClose fires on socket close; unsubscribe stops delivery", () => {
  const client = new WsClient("sess-1");
  const fake = new FakeSocket();
  client.socketFactory = () => fake;
  client.connect();

  const closed = vi.fn();
  const off = client.onClose(closed);
  fake.onclose!();
  expect(closed).toHaveBeenCalledTimes(1);

  off();
  fake.onclose!();
  expect(closed).toHaveBeenCalledTimes(1); // no further delivery after unsubscribe
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
