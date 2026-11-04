import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import ThinkControls from "./ThinkControls";
import { useThinkStore } from "../stores/thinkStore";
import { useSessionStore, setSessionDeps, resetSessionDeps } from "../session/sessionStore";

let fake: { send: ReturnType<typeof vi.fn> } & Record<string, unknown>;

beforeEach(async () => {
  resetSessionDeps();
  useSessionStore.getState().stop();
  useThinkStore.getState().reset();
  fake = {
    send: vi.fn(), sendBinary: vi.fn(), connect: vi.fn(), close: vi.fn(),
    on: () => () => {}, onBinary: () => () => {}, onOpen: () => () => {}, onClose: () => () => {},
  };
  setSessionDeps({
    createSession: () => Promise.resolve("s"),
    createClient: () => fake as unknown as import("../client/wsClient").WsClient,
  });
  useSessionStore.getState().start();
  await vi.waitFor(() => expect(useSessionStore.getState().sessionId).toBe("s"));
  useSessionStore.setState({ status: "connected" });
  useThinkStore.setState({ supported: true, enabled: false });
});

test("renders Think toggle with aria-pressed reflecting enabled", () => {
  useThinkStore.setState({ enabled: true });
  render(<ThinkControls />);
  expect(screen.getByRole("button", { name: "Think" })).toHaveAttribute("aria-pressed", "true");
});

test("clicking sends control:think with the negated state", async () => {
  render(<ThinkControls />);
  await userEvent.click(screen.getByRole("button", { name: "Think" }));
  expect(fake.send).toHaveBeenCalledWith({ channel: "control", type: "think", payload: { enabled: true } });
});

test("disabled with title=reason when unsupported", () => {
  useThinkStore.setState({ supported: false, reason: "qwen3 can't think" });
  render(<ThinkControls />);
  const b = screen.getByRole("button", { name: "Think" });
  expect(b).toBeDisabled();
  expect(b).toHaveAttribute("title", "qwen3 can't think");
});

test("disabled when session is not connected", () => {
  useSessionStore.setState({ status: "disconnected" });
  render(<ThinkControls />);
  expect(screen.getByRole("button", { name: "Think" })).toBeDisabled();
});

test("shows voiceNotice as status", () => {
  useThinkStore.setState({ voiceNotice: "Heard “think on”" });
  render(<ThinkControls />);
  expect(screen.getByRole("status")).toHaveTextContent("Heard “think on”");
});
