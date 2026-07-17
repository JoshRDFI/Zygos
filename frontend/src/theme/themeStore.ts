import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemeName = "instrument" | "study" | "quiet-os";
export type Mode = "light" | "dark" | "system";

export const THEMES: ThemeName[] = ["instrument", "study", "quiet-os"];
export const MODES: Mode[] = ["light", "dark", "system"];

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
    { name: "zygos.theme" },
  ),
);
