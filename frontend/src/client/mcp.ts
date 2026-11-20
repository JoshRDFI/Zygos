import type { McpView, PlannedServer } from "./types";

export const FORBIDDEN_TEXT = "this page isn't allowed to change Zygos — open it from the Zygos address";

/** A refused /mcp request. `notes` carries the per-server notes of an add where every server was refused. */
export class McpError extends Error {
  constructor(readonly status: number, readonly detail: string, readonly notes: string[] = []) {
    super(detail);
  }
}

export interface NotedView { view: McpView; notes: string[] }
export interface SaveResult { view: McpView; notes: string[]; listing: string[] }

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    ...(body === undefined ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }),
  });
  if (res.ok) return (await res.json()) as T;
  let parsed: { detail?: unknown; notes?: unknown } = {};
  try { parsed = await res.json(); } catch { /* non-JSON error body */ }
  const detail = res.status === 403
    ? FORBIDDEN_TEXT
    : typeof parsed.detail === "string" ? parsed.detail : `request failed: ${res.status}`;
  const notes = Array.isArray(parsed.notes) ? parsed.notes.filter((n): n is string => typeof n === "string") : [];
  throw new McpError(res.status, detail, notes);
}

const seg = encodeURIComponent;
const serverPath = (name: string) => `/mcp/servers/${seg(name)}`;
const toolPath = (zname: string) => `/mcp/tools/${seg(zname)}`;

export const getMcp = (): Promise<McpView> => send("GET", "/mcp");

export const planAdd = (text: string): Promise<{ servers: PlannedServer[]; problems: string[] }> =>
  send("POST", "/mcp/plan", { text });

export const saveServers = (text: string, replaces: string[]): Promise<SaveResult> =>
  send("POST", "/mcp/servers", { text, confirm: true, replaces });

export const removeServer = (name: string): Promise<NotedView> => send("DELETE", serverPath(name));

export const setServerOn = (name: string, on: boolean): Promise<McpView> =>
  send("PUT", `${serverPath(name)}/${on ? "on" : "off"}`);

export const setToolOn = (zname: string, on: boolean): Promise<McpView> =>
  send("PUT", `${toolPath(zname)}/${on ? "on" : "off"}`);

export const setServerTrust = (name: string, trusted: boolean): Promise<McpView> =>
  send(trusted ? "PUT" : "DELETE", `${serverPath(name)}/trust`);

export const setToolTrust = (zname: string, trusted: boolean): Promise<McpView> =>
  send(trusted ? "PUT" : "DELETE", `${toolPath(zname)}/trust`);

/** The value goes out in the request body once; the answer is the view, which reads `set`. */
export const setSecret = (name: string, secret: string, value: string): Promise<McpView> =>
  send("PUT", `${serverPath(name)}/secrets/${seg(secret)}`, { value });

export const setTimeout_ = (name: string, timeoutS: number): Promise<NotedView> =>
  send("PUT", `${serverPath(name)}/timeout`, { timeout_s: timeoutS });

export const refreshMcp = (): Promise<McpView> => send("POST", "/mcp/refresh");
