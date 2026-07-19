import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeName = "instrument" | "study" | "quiet-os";
export type Mode = "light" | "dark" | "system";

export const THEMES: ThemeName[] = ["instrument", "study", "quiet-os"];
export const MODES: Mode[] = ["light", "dark", "system"];
// Single source for the persisted-theme storage key; also referenced by the
// pre-hydration script in index.html (guarded by initTheme.test.ts).
export const THEME_STORAGE_KEY = "zygos.theme";

interface ThemeState {
  theme: ThemeName;
  mode: Mode;
  setTheme: (t: ThemeName) => void;
  setMode: (m: Mode) => void;
}

export const useThemeStore = create<ThemeState>()(
  persist(
    (set) => ({
      theme: "instrument",
      mode: "dark",
      setTheme: (theme) => set({ theme }),
      setMode: (mode) => set({ mode }),
    }),
    { name: THEME_STORAGE_KEY },
  ),
);
