import { render } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { resolveMode, useApplyTheme } from "./useApplyTheme";
import { useThemeStore } from "./themeStore";

beforeEach(() => {
  useThemeStore.setState({ theme: "instrument", mode: "dark" });
  vi.stubGlobal("matchMedia", (q: string) => ({
    matches: false, media: q, addEventListener: () => {}, removeEventListener: () => {},
    addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => false,
  }));
});

test("resolveMode maps system to a concrete mode", () => {
  expect(resolveMode("dark")).toBe("dark");
  expect(resolveMode("light")).toBe("light");
  expect(resolveMode("system")).toBe("light"); // matchMedia stub → not dark
});

function Probe() {
  useApplyTheme();
  return null;
}

test("useApplyTheme writes data-theme and data-mode to <html>", () => {
  useThemeStore.setState({ theme: "study", mode: "light" });
  render(<Probe />);
  expect(document.documentElement.getAttribute("data-theme")).toBe("study");
  expect(document.documentElement.getAttribute("data-mode")).toBe("light");
});
