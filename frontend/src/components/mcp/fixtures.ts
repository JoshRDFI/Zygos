import type { McpView, ServerView, ToolView } from "../../client/types";

export const tool = (o: Partial<ToolView> = {}): ToolView => ({
  zname: "archon__find_tasks", server_tool: "find_tasks", description: "", on: true,
  trust: "asks", was: null, now: null, schema_changed: false, claims: [], problem: null, ...o,
});

export const server = (o: Partial<ServerView> = {}): ServerView => ({
  name: "archon", transport: "http", local: false, runs: "http://localhost:8051/mcp", on: true,
  status: "reachable", status_word: "reachable", detail: null, status_at: null, era: null,
  exit_code: null, stderr_tail: null, timeout_s: 120, trusted_server: false,
  env_names: [], header_names: ["Authorization"], secrets: { Authorization: "set" }, secret_reasons: {},
  secrets_note: null, tools: [tool()], tools_on: 1, ...o,
});

export const view = (servers: ServerView[] = [server()], o: Partial<McpView> = {}): McpView => ({
  installed: true, servers, tools_on: servers.reduce((n, s) => n + s.tools_on, 0), warn: false, warning: null, ...o,
});
