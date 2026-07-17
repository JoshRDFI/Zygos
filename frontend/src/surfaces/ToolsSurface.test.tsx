import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ToolsSurface from "./ToolsSurface";
import * as rest from "../client/rest";

beforeEach(() => {
  vi.spyOn(rest, "getManifest").mockResolvedValue({
    lifecycle_stage: "running", capabilities: {},
    plugins: [
      { kind: "tool", name: "http_fetch", module: "zygos.tools.http:HttpFetch" },
      { kind: "provider", name: "primary", module: "zygos.providers.ollama:Ollama" },
    ],
    primary_route: { provider: "ollama", model: "qwen3" }, fallback_routes: [],
    reasoning_enabled: false, versions: {}, voice: null,
  });
});
afterEach(() => vi.restoreAllMocks());

test("lists only tool-kind plugins", async () => {
  render(<ToolsSurface />);
  await waitFor(() => expect(screen.getByText(/http_fetch/)).toBeInTheDocument());
  expect(screen.queryByText(/Ollama/)).not.toBeInTheDocument();
});
