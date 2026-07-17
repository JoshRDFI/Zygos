import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test } from "vitest";
import Shell from "./Shell";
import { SURFACES } from "./LeftRail";
import { useLayoutStore } from "./layoutStore";

beforeEach(() => useLayoutStore.setState({ contextPanelOpen: false }));

function renderShell() {
  return render(<MemoryRouter initialEntries={["/"]}><Shell /></MemoryRouter>);
}

test("renders the Zygos wordmark and all seven rail surfaces", () => {
  renderShell();
  expect(screen.getByText("Zygos")).toBeInTheDocument();
  for (const s of SURFACES) expect(screen.getByRole("link", { name: s.label })).toBeInTheDocument();
});

test("context panel is closed by default and opens on toggle", async () => {
  renderShell();
  expect(screen.queryByRole("heading", { name: "Context" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Toggle context panel" }));
  expect(screen.getByRole("heading", { name: "Context" })).toBeInTheDocument();
});
