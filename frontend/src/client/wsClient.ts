import type { Frame } from "./types";

export interface WebSocketLike {
  binaryType: string;
  send(data: string | ArrayBufferView): void;
  close(): void;
  onmessage: ((e: { data: string | ArrayBuffer }) => void) | null;
  onopen: (() => void) | null;
  onclose: (() => void) | null;
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

// Cap the pre-open buffer so a socket stuck in CONNECTING (unreachable backend)
// while audio streams can't grow memory without bound; keep the most recent.
const MAX_PREOPEN = 4096;

export class WsClient {
  socketFactory: (url: string) => WebSocketLike = (url) => new WebSocket(url) as WebSocketLike;
  private socket: WebSocketLike | null = null;
  private handlers = new Map<string, Set<Handler>>();
  private binaryHandlers = new Set<BinaryHandler>();
  private openHandlers = new Set<() => void>();
  private closeHandlers = new Set<() => void>();
  private preOpenQueue: Array<string | ArrayBufferView> = [];
  private readonly url: string;

  constructor(sessionId: string, wsUrl?: string) {
    this.url = wsUrl ?? `ws://${location.host}/ws/session/${sessionId}`;
  }

  connect(): void {
    this.preOpenQueue = []; // never replay frames buffered against a prior socket
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
    socket.onopen = () => {
      this.flushPreOpen();
      this.openHandlers.forEach((h) => h());
    };
    socket.onclose = () => this.closeHandlers.forEach((h) => h());
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

  onOpen(handler: () => void): () => void {
    this.openHandlers.add(handler);
    return () => this.openHandlers.delete(handler);
  }

  onClose(handler: () => void): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  send(frame: Frame): void {
    // Serialize only when the frame can actually be sent or buffered.
    if (this.socket && (this.socket.readyState === 0 || this.socket.readyState === 1)) {
      this.dispatchSend(JSON.stringify(frame));
    }
  }

  sendBinary(bytes: Uint8Array): void {
    this.dispatchSend(bytes);
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
    this.preOpenQueue = [];
  }

  // Send now if open; buffer if the socket is still connecting (so a message
  // typed before onopen isn't silently dropped); drop otherwise (closing/closed).
  private dispatchSend(data: string | ArrayBufferView): void {
    if (!this.socket) return;
    if (this.socket.readyState === 1) {
      this.socket.send(data);
    } else if (this.socket.readyState === 0) {
      this.preOpenQueue.push(data);
      if (this.preOpenQueue.length > MAX_PREOPEN) this.preOpenQueue.shift();
    }
  }

  private flushPreOpen(): void {
    if (!this.socket || this.socket.readyState !== 1) return;
    const queued = this.preOpenQueue;
    this.preOpenQueue = [];
    for (const data of queued) this.socket.send(data);
  }

  private dispatch(frame: Frame): void {
    this.handlers.get(frameKey(frame))?.forEach((h) => h(frame));
  }
}
