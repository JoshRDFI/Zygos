import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";
import { computeThemeAttrs } from "./initTheme";
import { MODES, THEMES, THEME_STORAGE_KEY } from "./themeStore";

test("defaults to instrument/dark when nothing is persisted", () => {
  expect(computeThemeAttrs(null, false)).toEqual({ theme: "instrument", mode: "dark" });
});

test("reads a persisted theme + explicit mode", () => {
  const raw = JSON.stringify({ state: { theme: "study", mode: "light" }, version: 0 });
  expect(computeThemeAttrs(raw, true)).toEqual({ theme: "study", mode: "light" });
});

test("resolves system mode against the prefers-color-scheme signal", () => {
  const raw = JSON.stringify({ state: { theme: "quiet-os", mode: "system" }, version: 0 });
  expect(computeThemeAttrs(raw, true)).toEqual({ theme: "quiet-os", mode: "dark" });
  expect(computeThemeAttrs(raw, false)).toEqual({ theme: "quiet-os", mode: "light" });
});

test("falls back to defaults on malformed JSON or unknown values", () => {
  expect(computeThemeAttrs("not json", false)).toEqual({ theme: "instrument", mode: "dark" });
  const bogus = JSON.stringify({ state: { theme: "neon", mode: "sideways" }, version: 0 });
  expect(computeThemeAttrs(bogus, false)).toEqual({ theme: "instrument", mode: "dark" });
});

// The blocking pre-hydration script in index.html re-implements this resolver
// inline (it can't import a module), so guard against the two copies drifting.
test("index.html pre-hydration script covers every theme, mode, and the storage key", () => {
  const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");
  expect(html).toContain(THEME_STORAGE_KEY);
  for (const t of THEMES) expect(html).toContain(`"${t}"`);
  for (const m of MODES) expect(html).toContain(`"${m}"`);
});
