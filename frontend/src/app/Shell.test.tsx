import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import Shell from "./Shell";
import { SURFACES } from "./LeftRail";
import { useLayoutStore } from "./layoutStore";
import * as rest from "../client/rest";
import { WsClient } from "../client/wsClient";

beforeEach(() => {
  useLayoutStore.setState({ contextPanelOpen: false });
  // ChatSurface (mounted at "/") creates a session and connects a WsClient on
  // mount; keep that from touching the network in jsdom.
  vi.spyOn(rest, "createSession").mockResolvedValue("sess-test");
  vi.spyOn(WsClient.prototype, "connect").mockImplementation(function (this: WsClient) {});
});
afterEach(() => vi.restoreAllMocks());

function renderShell() {
  return render(<MemoryRouter initialEntries={["/"]}><Shell /></MemoryRouter>);
}

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
