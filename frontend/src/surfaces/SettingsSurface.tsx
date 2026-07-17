import { MODES, THEMES, useThemeStore } from "../theme/themeStore";

export default function SettingsSurface() {
  const { theme, mode, setTheme, setMode } = useThemeStore();
  return (
    <div className="p-6 max-w-md">
      <h1 className="text-lg font-mono mb-6">Settings</h1>
      <div className="space-y-4">
        <label className="flex items-center justify-between gap-4">
          <span>Theme</span>
          <select
            aria-label="Theme"
            className="bg-surface-2 border border-border rounded px-2 py-1 text-text"
            value={theme}
            onChange={(e) => setTheme(e.target.value as (typeof THEMES)[number])}
          >
            {THEMES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        <label className="flex items-center justify-between gap-4">
          <span>Mode</span>
          <select
            aria-label="Mode"
            className="bg-surface-2 border border-border rounded px-2 py-1 text-text"
            value={mode}
            onChange={(e) => setMode(e.target.value as (typeof MODES)[number])}
          >
            {MODES.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </label>
      </div>
    </div>
  );
}
