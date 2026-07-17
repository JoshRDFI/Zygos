import type { Frame } from "./types";

export interface WebSocketLike {
  binaryType: string;
  send(data: string | ArrayBufferView): void;
  close(): void;
  onmessage: ((e: { data: string | ArrayBuffer }) => void) | null;
  onopen: (() => void) | null;
  readyState: number;
}

export function frameKey(f: Frame): string {
  return `${f.channel}:${f.type}`;
}

export function parseFrame(raw: string): Frame | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.channel !== "string" || typeof d.type !== "string") return null;
  return { channel: d.channel, type: d.type, payload: (d.payload as Record<string, unknown>) ?? {} };
}

type Handler = (f: Frame) => void;
type BinaryHandler = (data: ArrayBuffer) => void;

export class WsClient {
  socketFactory: (url: string) => WebSocketLike = (url) => new WebSocket(url) as WebSocketLike;
  private socket: WebSocketLike | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private binaryHandlers = new Set<BinaryHandler>();
  private readonly url: string;

  constructor(sessionId: string, wsUrl?: string) {
    this.url = wsUrl ?? `ws://${location.host}/ws/session/${sessionId}`;
  }

  connect(): void {
    const socket = this.socketFactory(this.url);
    socket.binaryType = "arraybuffer";
    socket.onmessage = (e) => {
      if (typeof e.data === "string") {
        const frame = parseFrame(e.data);
        if (frame) this.dispatch(frame);
      } else {
        this.binaryHandlers.forEach((h) => h(e.data as ArrayBuffer));
      }
    };
    this.socket = socket;
  }

  on(key: string, handler: Handler): () => void {
    let set = this.handlers.get(key);
    if (!set) {
      set = new Set();
      this.handlers.set(key, set);
    }
    set.add(handler);
    return () => set!.delete(handler);
  }

  onBinary(handler: BinaryHandler): () => void {
    this.binaryHandlers.add(handler);
    return () => this.binaryHandlers.delete(handler);
  }

  send(frame: Frame): void {
    if (this.socket && this.socket.readyState === 1) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  sendBinary(bytes: Uint8Array): void {
    if (this.socket && this.socket.readyState === 1) {
      this.socket.send(bytes);
    }
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }

  private dispatch(frame: Frame): void {
    this.handlers.get(frameKey(frame))?.forEach((h) => h(frame));
  }
}
