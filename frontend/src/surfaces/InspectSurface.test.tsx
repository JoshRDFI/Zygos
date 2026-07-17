import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import InspectSurface from "./InspectSurface";
import * as rest from "../client/rest";

beforeEach(() => {
  vi.spyOn(rest, "getManifest").mockResolvedValue({
    lifecycle_stage: "running",
    capabilities: {},
    plugins: [{ kind: "provider", name: "primary", module: "zygos.providers.ollama:Ollama" }],
    primary_route: { provider: "ollama", model: "qwen3" },
    fallback_routes: [],
    reasoning_enabled: false,
    versions: { zygos: "0.1.0", python: "3.12.0" },
    voice: null,
  });
});
afterEach(() => vi.restoreAllMocks());

test("renders live manifest fields", async () => {
  render(<InspectSurface />);
  await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  expect(screen.getByText(/qwen3/)).toBeInTheDocument();
  expect(screen.getByText(/zygos.providers.ollama:Ollama/)).toBeInTheDocument();
});
