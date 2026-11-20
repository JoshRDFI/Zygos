import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ToolsSurface from "./ToolsSurface";
import * as rest from "../client/rest";
import * as mcp from "../client/mcp";

beforeEach(() => {
  vi.spyOn(rest, "getManifest").mockResolvedValue({
    lifecycle_stage: "running", capabilities: {},
    plugins: [
      { kind: "tools", name: "http_fetch", module: "zygos.tools.http:HttpFetch" },
      { kind: "providers", name: "primary", module: "zygos.providers.ollama:Ollama" },
    ],
    primary_route: { provider: "ollama", model: "qwen3" }, fallback_routes: [],
    reasoning_enabled: false, versions: {}, voice: null, thinking: null,
  });
});
afterEach(() => vi.restoreAllMocks());

test("lists only tool-kind plugins", async () => {
  render(<ToolsSurface />);
  await waitFor(() => expect(screen.getByText(/http_fetch/)).toBeInTheDocument());
  expect(screen.queryByText(/Ollama/)).not.toBeInTheDocument();
});

test("built-in tools list still renders below the MCP section", async () => {
  vi.spyOn(mcp, "getMcp").mockResolvedValue({ installed: false, servers: [], tools_on: 0, warn: false, warning: null });
  render(<ToolsSurface />);
  expect(await screen.findByText(/MCP support not installed/)).toBeInTheDocument();
  expect(screen.getByText(/http_fetch/)).toBeInTheDocument();
  expect(screen.getByText("Built-in tools")).toBeInTheDocument();
});
