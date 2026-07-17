import { create } from "zustand";

interface LayoutState {
  contextPanelOpen: boolean;
  toggleContextPanel: () => void;
}

export const useLayoutStore = create<LayoutState>((set) => ({
  contextPanelOpen: false,
  toggleContextPanel: () => set((s) => ({ contextPanelOpen: !s.contextPanelOpen })),
}));
