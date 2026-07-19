import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ChatSurface from "./ChatSurface";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore, setSessionDeps, resetSessionDeps } from "../session/sessionStore";

let createSession: ReturnType<typeof vi.fn>;
let fake: { send: ReturnType<typeof vi.fn> } & Record<string, unknown>;

function makeFakeClient() {
  return {
    send: vi.fn(), sendBinary: vi.fn(), connect: vi.fn(), close: vi.fn(),
    on: () => () => {}, onBinary: () => () => {}, onOpen: () => () => {}, onClose: () => () => {},
  };
}

beforeEach(() => {
  useSessionStore.getState().stop();
  useChatStore.getState().reset();
  fake = makeFakeClient();
  createSession = vi.fn(() => Promise.resolve("sess-1"));
  setSessionDeps({
    createSession,
    createClient: () => fake as unknown as import("../client/wsClient").WsClient,
  });
});
afterEach(() => resetSessionDeps());

test("submitting a message renders it and sends a user_message frame", async () => {
  useSessionStore.getState().start();
  await vi.waitFor(() => expect(useSessionStore.getState().sessionId).toBe("sess-1"));
  render(<ChatSurface />);

  await userEvent.type(screen.getByRole("textbox"), "hello there");
  await userEvent.click(screen.getByRole("button", { name: "Send" }));

  expect(screen.getByText("hello there")).toBeInTheDocument();
  expect(fake.send).toHaveBeenCalledWith({
    channel: "chat", type: "user_message", payload: { text: "hello there" },
  });
});

test("disconnected status disables Send and shows a note", () => {
  useSessionStore.setState({ status: "disconnected" });
  render(<ChatSurface />);
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(screen.getByText(/disconnected/i)).toBeInTheDocument();
});

test("error status shows Retry which restarts the session", async () => {
  useSessionStore.setState({ status: "error" });
  render(<ChatSurface />);
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(createSession).toHaveBeenCalledTimes(1);
});
