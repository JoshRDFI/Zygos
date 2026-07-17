import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ModelsSurface from "./ModelsSurface";
import * as rest from "../client/rest";

const manifest = {
  lifecycle_stage: "running", capabilities: {},
  plugins: [{ kind: "tool", name: "http_fetch", module: "zygos.tools.http:HttpFetch" }],
  primary_route: { provider: "ollama", model: "qwen3" },
  fallback_routes: [{ provider: "anthropic", model: "claude-sonnet-5" }],
  reasoning_enabled: false, versions: {}, voice: null,
};

beforeEach(() => { vi.spyOn(rest, "getManifest").mockResolvedValue(manifest); });
afterEach(() => vi.restoreAllMocks());

test("lists routes and marks selection as not yet available", async () => {
  render(<ModelsSurface />);
  await waitFor(() => expect(screen.getByText(/qwen3/)).toBeInTheDocument());
  expect(screen.getByText(/claude-sonnet-5/)).toBeInTheDocument();
  expect(screen.getByText(/coming later/i)).toBeInTheDocument();
});
