import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import VoiceControls from "./VoiceControls";
import { useVoiceStore } from "../voice/voiceStore";
import { useSessionStore } from "../session/sessionStore";

beforeEach(() => {
  localStorage.clear();
  useVoiceStore.setState({ voiceEnabled: false, micOn: false, speakerOn: false, alwaysOn: false, warning: null });
  // Voice controls are usable only while the session is live; default the tests
  // that exercise the enabled state to a connected session.
  useSessionStore.setState({ status: "connected" });
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

test("reflects on-state through aria-pressed=true", () => {
  useVoiceStore.setState({ voiceEnabled: true, micOn: true, speakerOn: true, alwaysOn: false });
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Voice" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Mic" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Speaker" })).toHaveAttribute("aria-pressed", "true");
});

test("session offline disables Mic, Always-on, and Speaker even when Voice is on", () => {
  useVoiceStore.setState({ voiceEnabled: true });
  useSessionStore.setState({ status: "disconnected" });
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Mic" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Always-on" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Speaker" })).toBeDisabled();
  // Voice master stays clickable — it is a local preference, not a socket action.
  expect(screen.getByRole("button", { name: "Voice" })).toBeEnabled();
});

test("session reconnecting (not yet connected) keeps socket controls disabled", () => {
  useVoiceStore.setState({ voiceEnabled: true });
  useSessionStore.setState({ status: "connecting" });
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Mic" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Speaker" })).toBeDisabled();
});

test("warning renders when set in the store", () => {
  useVoiceStore.setState({ warning: "Voice is active elsewhere." });
  render(<VoiceControls />);
  expect(screen.getByRole("status")).toHaveTextContent("Voice is active elsewhere.");
});
