import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import DoctorSurface from "./DoctorSurface";
import * as rest from "../client/rest";

beforeEach(() => {
  vi.spyOn(rest, "getHealth").mockResolvedValue({
    routes: [{ provider: "ollama", model: "qwen3", circuit: "closed" }],
    embedder: { backend: "fastembed", model: "bge-small", state: "not_probed" },
    active_sessions: 2,
  });
});
afterEach(() => vi.restoreAllMocks());

test("renders live health and probes on demand", async () => {
  render(<DoctorSurface />);
  await waitFor(() => expect(screen.getByText(/active sessions: 2/i)).toBeInTheDocument());
  expect(screen.getByText(/closed/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /probe embedder/i }));
  expect(rest.getHealth).toHaveBeenLastCalledWith(true);
});
