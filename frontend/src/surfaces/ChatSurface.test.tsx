import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ChatSurface from "./ChatSurface";
import { useChatStore } from "../stores/chatStore";
import * as rest from "../client/rest";
import { WsClient } from "../client/wsClient";

beforeEach(() => {
  useChatStore.getState().reset();
  vi.spyOn(rest, "createSession").mockResolvedValue("sess-test");
  // Never open a real socket in jsdom.
  vi.spyOn(WsClient.prototype, "connect").mockImplementation(function (this: WsClient) {});
});
afterEach(() => vi.restoreAllMocks());

test("submitting a message renders it and sends a user_message frame", async () => {
  const sendSpy = vi.spyOn(WsClient.prototype, "send").mockImplementation(() => {});
  render(<ChatSurface />);
  await waitFor(() => expect(rest.createSession).toHaveBeenCalled());

  await userEvent.type(screen.getByRole("textbox"), "hello there");
  await userEvent.click(screen.getByRole("button", { name: "Send" }));

  expect(screen.getByText("hello there")).toBeInTheDocument();
  expect(sendSpy).toHaveBeenCalledWith({
    channel: "chat", type: "user_message", payload: { text: "hello there" },
  });
});
