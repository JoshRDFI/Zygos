import { act, render, screen, waitFor } from "@testing-library/react";
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

test("shows an error state when health fails to load, not perpetual loading", async () => {
  vi.spyOn(rest, "getHealth").mockRejectedValue(new Error("backend down"));
  render(<DoctorSurface />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
  expect(screen.getByRole("alert")).toHaveTextContent(/couldn.t load/i);
  expect(screen.queryByText(/loading health/i)).not.toBeInTheDocument();
});

test("a slow-failing earlier load does not clobber a newer successful result", async () => {
  let rejectFirst: (reason?: unknown) => void = () => {};
  const firstNeverResolves = new Promise<never>((_, rej) => { rejectFirst = rej; });
  vi.spyOn(rest, "getHealth")
    .mockReturnValueOnce(firstNeverResolves) // mount load(false): slow, will reject
    .mockResolvedValueOnce({                 // probe load(true): resolves first
      routes: [{ provider: "ollama", model: "qwen3", circuit: "closed" }],
      embedder: { backend: "fastembed", model: "bge-small", state: "not_probed" },
      active_sessions: 5,
    });

  render(<DoctorSurface />);
  await userEvent.click(screen.getByRole("button", { name: /probe embedder/i }));
  await waitFor(() => expect(screen.getByText(/active sessions: 5/i)).toBeInTheDocument());

  await act(async () => {
    rejectFirst(new Error("slow fail")); // the earlier request now fails, out of order
    await Promise.resolve();
  });
  expect(screen.queryByRole("alert")).not.toBeInTheDocument(); // stale failure ignored
  expect(screen.getByText(/active sessions: 5/i)).toBeInTheDocument();
});

test("renders live health and probes on demand", async () => {
  render(<DoctorSurface />);
  await waitFor(() => expect(screen.getByText(/active sessions: 2/i)).toBeInTheDocument());
  expect(screen.getByText(/closed/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /probe embedder/i }));
  expect(rest.getHealth).toHaveBeenLastCalledWith(true);
});
