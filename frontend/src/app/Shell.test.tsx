import { StrictMode } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Shell from "./Shell";
import { SURFACES } from "./LeftRail";
import { useLayoutStore } from "./layoutStore";
import { useSessionStore, setSessionDeps, resetSessionDeps } from "../session/sessionStore";

let createSession: ReturnType<typeof vi.fn>;

function makeFakeClient() {
  return {
    send: vi.fn(), sendBinary: vi.fn(), connect: vi.fn(), close: vi.fn(),
    on: () => () => {}, onBinary: () => () => {}, onOpen: () => () => {}, onClose: () => () => {},
  };
}

beforeEach(() => {
  useLayoutStore.setState({ contextPanelOpen: false });
  useSessionStore.getState().stop();
  createSession = vi.fn(() => Promise.resolve("sess-test"));
  setSessionDeps({
    createSession,
    createClient: () => makeFakeClient() as unknown as import("../client/wsClient").WsClient,
  });
});
afterEach(() => { resetSessionDeps(); vi.restoreAllMocks(); });

function renderShell() {
  return render(<MemoryRouter initialEntries={["/"]}><Shell /></MemoryRouter>);
}

test("Shell starts the session once on mount", async () => {
  renderShell();
  await vi.waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
});

test("Shell starts the session once under StrictMode double-invoke", async () => {
  render(
    <StrictMode>
      <MemoryRouter initialEntries={["/"]}>
        <Shell />
      </MemoryRouter>
    </StrictMode>,
  );
  await vi.waitFor(() => expect(createSession).toHaveBeenCalledTimes(1));
  // StrictMode mounts the effect, tears it down, and mounts it again; the
  // in-flight startPromise guard must swallow the second start(). Let any second
  // invocation settle, then confirm the session was still created only once.
  await Promise.resolve();
  expect(createSession).toHaveBeenCalledTimes(1);
});

test("renders the Zygos wordmark and all seven rail surfaces", () => {
  renderShell();
  expect(screen.getByText("Zygos")).toBeInTheDocument();
  for (const s of SURFACES) expect(screen.getByRole("link", { name: s.label })).toBeInTheDocument();
});

test("routes /settings to the Settings surface", () => {
  render(<MemoryRouter initialEntries={["/settings"]}><Shell /></MemoryRouter>);
  expect(screen.getByRole("heading", { name: "Settings" })).toBeInTheDocument();
});

test("context panel is closed by default and opens on toggle", async () => {
  renderShell();
  expect(screen.queryByRole("heading", { name: "Context" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Toggle context panel" }));
  expect(screen.getByRole("heading", { name: "Context" })).toBeInTheDocument();
});
