import { act, render as rtlRender, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import type { ReactElement } from "react";
import { useThinkStore } from "../stores/thinkStore";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import ChatSurface from "./ChatSurface";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore, setSessionDeps, resetSessionDeps } from "../session/sessionStore";

function render(ui: ReactElement) {
  return rtlRender(
    <MemoryRouter initialEntries={["/chat"]}>
      <Routes>
        <Route path="/chat" element={ui} />
        <Route path="/inspect" element={<div>INSPECT PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

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
  useThinkStore.getState().reset();
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

test("submitting before the session client exists adds nothing to the transcript and keeps the draft", async () => {
  createSession.mockImplementationOnce(() => new Promise<string>(() => {})); // never resolves -> rig stays null
  useSessionStore.getState().start();
  await vi.waitFor(() => expect(useSessionStore.getState().status).toBe("connecting"));
  render(<ChatSurface />);
  await userEvent.type(screen.getByRole("textbox"), "too early");
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
  expect(screen.queryByText("too early")).not.toBeInTheDocument();
  expect((screen.getByRole("textbox") as HTMLInputElement).value).toBe("too early");
});

async function startConnected() {
  useSessionStore.getState().start();
  await vi.waitFor(() => expect(useSessionStore.getState().sessionId).toBe("sess-1"));
}
const answered = (over: Record<string, unknown> = {}) => ({
  role: "assistant" as const, text: "answer", streaming: false,
  turnId: "t1", think: false, question: "why?", ...over,
});

test("Think it through re-asks with think and rethink_of", async () => {
  await startConnected();
  useThinkStore.setState({ supported: true });
  useChatStore.setState({ messages: [{ role: "user", text: "why?", streaming: false }, answered()] });
  const addReask = vi.spyOn(useChatStore.getState(), "addReask");
  render(<ChatSurface />);
  await userEvent.click(screen.getByRole("button", { name: "Think it through" }));
  expect(addReask).toHaveBeenCalledWith("why?");
  expect(fake.send).toHaveBeenCalledWith({
    channel: "chat", type: "user_message",
    payload: { text: "why?", think: true, rethink_of: "t1" },
  });
});

test("Think it through is disabled while any message is streaming", async () => {
  await startConnected();
  useThinkStore.setState({ supported: true });
  useChatStore.setState({ messages: [answered(), { role: "assistant", text: "", streaming: true, turnId: "t2", think: false }] });
  render(<ChatSurface />);
  for (const b of screen.getAllByRole("button", { name: "Think it through" })) expect(b).toBeDisabled();
});

test("Think it through is hidden on messages that already thought", () => {
  useThinkStore.setState({ supported: true });
  useChatStore.setState({ messages: [answered({ think: true })] });
  render(<ChatSurface />);
  expect(screen.queryByRole("button", { name: "Think it through" })).toBeNull();
});

test("Think it through is disabled with the reason when unsupported", () => {
  useThinkStore.setState({ supported: false, reason: "qwen3 can't think" });
  useChatStore.setState({ messages: [answered()] });
  render(<ChatSurface />);
  const b = screen.getByRole("button", { name: "Think it through" });
  expect(b).toBeDisabled();
  expect(b).toHaveAttribute("title", "qwen3 can't think");
});

test("streaming thinking message shows Thinking…", () => {
  useChatStore.setState({ messages: [answered({ streaming: true, think: true })] });
  render(<ChatSurface />);
  expect(screen.getByText("Thinking…")).toBeInTheDocument();
});

test("finished thinking message shows duration; click selects turn and goes to Inspect", async () => {
  useChatStore.setState({ messages: [answered({ think: true, thinkingMs: 4200 })] });
  render(<ChatSurface />);
  await userEvent.click(screen.getByRole("button", { name: "thought for 4.2 s" }));
  expect(useThinkStore.getState().selectedTurnId).toBe("t1");
  expect(screen.getByText("INSPECT PAGE")).toBeInTheDocument();
});

test("a re-ask message is labelled with thinking", () => {
  useChatStore.setState({ messages: [answered({ think: true, rethinkOf: "t0" })] });
  render(<ChatSurface />);
  expect(screen.getByText("with thinking")).toBeInTheDocument();
});

test("thinking text never appears in the chat", () => {
  useThinkStore.setState({
    eventsByTurn: { t1: [{ turnId: "t1", step: "direct", index: 0, text: "SECRET-CHAIN", truncated: false, chars: 12, elapsedMs: 5 }] },
    turnOrder: ["t1"],
  });
  useChatStore.setState({ messages: [answered({ think: true, thinkingMs: 100 })] });
  const { container } = render(<ChatSurface />);
  expect(container.textContent).not.toContain("SECRET-CHAIN");
});

test("after a failed turn, Think it through on an earlier answer is enabled (I3)", async () => {
  await startConnected();
  useThinkStore.setState({ supported: true });
  useChatStore.setState({ messages: [{ role: "user", text: "why?", streaming: false }, answered()] });
  const s = useChatStore.getState();
  s.addUser("next");
  s.onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "t2", think: true } });
  s.onFrame({ channel: "chat", type: "error", payload: { message: "generation failed" } });
  render(<ChatSurface />);
  expect(screen.queryByText("Thinking…")).toBeNull();
  expect(screen.getByRole("button", { name: "Think it through" })).toBeEnabled();
});

test("a downgraded re-ask is not labelled with thinking and shows why (M3)", () => {
  useChatStore.setState({
    messages: [answered({ think: false, rethinkOf: "t0", thinkUnsupportedReason: "qwen3 can't think" })],
  });
  render(<ChatSurface />);
  expect(screen.queryByText("with thinking")).toBeNull();
  expect(screen.getByText("thinking unavailable — qwen3 can't think")).toBeInTheDocument();
});

test("no unsupported note without a reason (M3)", () => {
  useChatStore.setState({ messages: [answered()] });
  const { container } = render(<ChatSurface />);
  expect(container.textContent).not.toContain("thinking unavailable");
});

// ---- RFC-0013 phase 2 ----
test("a finished reply shows 'answered by <model>'; a null model shows nothing", async () => {
  const { useChatStore } = await import("../stores/chatStore");
  useChatStore.getState().reset();
  const f = (await import("../stores/fixtures/model-turn-frames.json")).default;
  const chatFrames = f.turn_with_load_all_frames.filter((x) => x.channel === "chat");
  chatFrames.forEach((x) => useChatStore.getState().onFrame(x as never));
  render(<ChatSurface />);
  expect(screen.getByText("answered by qwen3:8b")).toBeInTheDocument();
  expect(screen.queryByText(/loading qwen3:8b/)).toBeNull();
  act(() => {
    useChatStore.getState().reset();
    useChatStore.getState().onFrame({ channel: "chat", type: "turn.start", payload: { turn_id: "n" } } as never);
    useChatStore.getState().onFrame({ channel: "chat", type: "turn.end", payload: { text: "hi", model: null } } as never);
  });
  expect(screen.queryByText(/answered by/)).toBeNull();
  useChatStore.getState().reset();
});

test("a pending reply shows 'loading <model>…' until the first token", async () => {
  const { useChatStore } = await import("../stores/chatStore");
  useChatStore.getState().reset();
  const f = (await import("../stores/fixtures/model-turn-frames.json")).default;
  const chatFrames = f.turn_with_load_all_frames.filter((x) => x.channel === "chat");
  chatFrames.slice(0, 2).forEach((x) => useChatStore.getState().onFrame(x as never));
  render(<ChatSurface />);
  expect(screen.getByText("loading qwen3:8b…")).toBeInTheDocument();
  act(() => useChatStore.getState().onFrame(chatFrames[2] as never));
  expect(screen.queryByText("loading qwen3:8b…")).toBeNull();
  useChatStore.getState().reset();
});

test("renders tool cards above the assistant text", () => {
  useChatStore.setState({
    messages: [{
      role: "assistant", text: "REPLY TEXT", streaming: false,
      tools: [{ callId: "c1", tool: "find_tasks", server: "archon", args: {}, status: "done" }],
    }],
  });
  const { container } = render(<ChatSurface />);
  const html = container.innerHTML;
  expect(html.indexOf("find_tasks")).toBeGreaterThan(-1);
  expect(html.indexOf("find_tasks")).toBeLessThan(html.indexOf("REPLY TEXT"));
});
