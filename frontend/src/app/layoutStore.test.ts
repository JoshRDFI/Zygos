import { beforeEach, expect, test } from "vitest";
import { useLayoutStore } from "./layoutStore";

beforeEach(() => useLayoutStore.setState({ contextPanelOpen: false }));

test("context panel is closed by default and toggles", () => {
  expect(useLayoutStore.getState().contextPanelOpen).toBe(false);
  useLayoutStore.getState().toggleContextPanel();
  expect(useLayoutStore.getState().contextPanelOpen).toBe(true);
});
