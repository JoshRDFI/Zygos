import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import VoiceControls from "./VoiceControls";

test("renders four disabled voice controls", () => {
  render(<VoiceControls />);
  for (const name of ["Mic", "Always-on", "Voice", "Speaker"]) {
    const btn = screen.getByRole("button", { name });
    expect(btn).toBeDisabled();
  }
});
