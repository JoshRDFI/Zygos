import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import VoiceControls from "./VoiceControls";
import { useVoiceStore } from "../voice/voiceStore";

beforeEach(() => {
  localStorage.clear();
  useVoiceStore.setState({ voiceEnabled: false, micOn: false, speakerOn: false, alwaysOn: false, warning: null });
});

test("Always-on is gated by Voice master and toggles aria-pressed", async () => {
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Always-on" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Voice" }));
  const always = screen.getByRole("button", { name: "Always-on" });
  expect(always).toBeEnabled();
  expect(always).toHaveAttribute("aria-pressed", "false");
});

test("enabling always-on (via store) disables the Mic button and shows a listening indicator", () => {
  useVoiceStore.setState({ voiceEnabled: true, alwaysOn: true });
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Mic" })).toBeDisabled();
  expect(screen.getByText(/listening/i)).toBeInTheDocument();
});

test("Voice master gates Mic and Speaker", async () => {
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Mic" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Speaker" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Voice" }));
  expect(screen.getByRole("button", { name: "Mic" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Speaker" })).toBeEnabled();
});

test("warning renders when set in the store", () => {
  useVoiceStore.setState({ warning: "Voice is active elsewhere." });
  render(<VoiceControls />);
  expect(screen.getByRole("status")).toHaveTextContent("Voice is active elsewhere.");
});
