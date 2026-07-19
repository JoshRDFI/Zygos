import { MODES, THEMES, type Mode, type ThemeName } from "./themeStore";

export interface ThemeAttrs {
  theme: ThemeName;
  mode: "light" | "dark";
}

const DEFAULT_THEME: ThemeName = "instrument";
const DEFAULT_MODE: "light" | "dark" = "dark";

/**
 * Resolve the data-theme / data-mode attributes to stamp on <html> before first
 * paint, from the zustand-persisted `zygos.theme` blob and the OS color-scheme
 * signal. Pure so it can be unit-tested; the same logic is hand-inlined as a
 * blocking <script> in index.html to avoid a flash-of-wrong-theme (keep in sync).
 */
export function computeThemeAttrs(raw: string | null, prefersDark: boolean): ThemeAttrs {
  let theme: ThemeName = DEFAULT_THEME;
  let mode: Mode = DEFAULT_MODE;
  try {
    const state = raw ? (JSON.parse(raw) as { state?: { theme?: unknown; mode?: unknown } }).state : undefined;
    if (state && THEMES.includes(state.theme as ThemeName)) theme = state.theme as ThemeName;
    if (state && MODES.includes(state.mode as Mode)) mode = state.mode as Mode;
  } catch {
    /* malformed storage — fall back to defaults */
  }
  const resolved = mode === "system" ? (prefersDark ? "dark" : "light") : mode;
  return { theme, mode: resolved };
}
