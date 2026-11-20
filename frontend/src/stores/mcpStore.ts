import { create } from "zustand";
import { McpError, getMcp } from "../client/mcp";
import type { McpView } from "../client/types";

type Outcome = McpView | { view: McpView; notes: string[] };

/** The control key of an add. What an add left is shown at section level once its panel
 * closes, so it stays only until the next action, whichever control that is. */
export const ADD_KEY = "add";

interface McpState {
  view: McpView | null;
  loading: boolean;
  loadError: string | null;
  /** The control key of the action in flight, e.g. "server:archon:on". */
  busy: string | null;
  /** Control key -> why its last action was refused. */
  errors: Record<string, string>;
  /** Control key -> notes its last action returned, shown under that control. */
  notes: Record<string, string[]>;
  load: () => Promise<void>;
  run: (key: string, action: () => Promise<Outcome>) => Promise<void>;
}

const message = (e: unknown) => (e instanceof McpError ? e.detail : e instanceof Error ? e.message : String(e));

export const useMcpStore = create<McpState>((set, get) => ({
  view: null,
  loading: false,
  loadError: null,
  busy: null,
  errors: {},
  notes: {},

  async load() {
    set({ loading: true });
    try {
      set({ view: await getMcp(), loadError: null, loading: false });
    } catch (e) {
      set({ loadError: message(e), loading: false });
    }
  },

  async run(key, action) {
    const { [key]: _e, [ADD_KEY]: _ae, ...errors } = get().errors;
    const { [key]: _n, [ADD_KEY]: _an, ...notes } = get().notes;
    set({ busy: key, errors, notes });
    try {
      const out = await action();
      const [view, got] = "view" in out ? [out.view, out.notes] : [out, []];
      set((s) => ({ view, notes: got.length ? { ...s.notes, [key]: got } : s.notes }));
    } catch (e) {
      const got = e instanceof McpError ? e.notes : [];
      set((s) => ({
        errors: { ...s.errors, [key]: message(e) },
        notes: got.length ? { ...s.notes, [key]: got } : s.notes,
      }));
      if (e instanceof McpError && e.status === 404) await get().load();
    } finally {
      set({ busy: null });
    }
  },
}));
