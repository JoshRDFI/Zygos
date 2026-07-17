import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import Placeholder from "./Placeholder";
import FilesSurface from "./FilesSurface";
import MemorySurface from "./MemorySurface";

test("Placeholder shows a consistent not-yet-wired marker", () => {
  render(<Placeholder title="Files" note="Document library backend lands later." />);
  expect(screen.getByText("Files")).toBeInTheDocument();
  expect(screen.getByTestId("placeholder-marker")).toBeInTheDocument();
});

test("Files and Memory surfaces are marked placeholders", () => {
  const { unmount } = render(<FilesSurface />);
  expect(screen.getByTestId("placeholder-marker")).toBeInTheDocument();
  unmount();
  render(<MemorySurface />);
  expect(screen.getByTestId("placeholder-marker")).toBeInTheDocument();
});
