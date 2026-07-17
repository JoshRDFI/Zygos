import { beforeEach, expect, test } from "vitest";
import { useThemeStore } from "./themeStore";

beforeEach(() => {
  localStorage.clear();
  useThemeStore.setState({ theme: "instrument", mode: "dark" });
});

test("defaults to instrument/dark", () => {
  expect(useThemeStore.getState().theme).toBe("instrument");
  expect(useThemeStore.getState().mode).toBe("dark");
});

test("setTheme and setMode update state and persist", () => {
  useThemeStore.getState().setTheme("study");
  useThemeStore.getState().setMode("system");
  expect(useThemeStore.getState().theme).toBe("study");
  expect(useThemeStore.getState().mode).toBe("system");
  expect(localStorage.getItem("zygos.theme")).toContain("study");
});
