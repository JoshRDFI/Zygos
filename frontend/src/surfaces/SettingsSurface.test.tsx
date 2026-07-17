import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test } from "vitest";
import SettingsSurface from "./SettingsSurface";
import { useThemeStore } from "../theme/themeStore";

beforeEach(() => useThemeStore.setState({ theme: "instrument", mode: "dark" }));

test("changing the theme select updates the store", async () => {
  render(<SettingsSurface />);
  await userEvent.selectOptions(screen.getByLabelText("Theme"), "study");
  expect(useThemeStore.getState().theme).toBe("study");
});

test("changing the mode select updates the store", async () => {
  render(<SettingsSurface />);
  await userEvent.selectOptions(screen.getByLabelText("Mode"), "light");
  expect(useThemeStore.getState().mode).toBe("light");
});
