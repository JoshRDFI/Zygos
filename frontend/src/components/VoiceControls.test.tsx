import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import VoiceControls from "./VoiceControls";
import { useVoiceStore } from "../voice/voiceStore";

beforeEach(() => {
  localStorage.clear();
  useVoiceStore.setState({ voiceEnabled: false, micOn: false, speakerOn: false, warning: null });
});

test("Always-on remains a disabled placeholder (1c)", () => {
  render(<VoiceControls />);
  expect(screen.getByRole("button", { name: "Always-on" })).toBeDisabled();
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
