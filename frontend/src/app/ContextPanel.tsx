import { useLayoutStore } from "./layoutStore";

export default function ContextPanel() {
  const open = useLayoutStore((s) => s.contextPanelOpen);
  const toggle = useLayoutStore((s) => s.toggleContextPanel);
  return (
    <>
      <button
        onClick={toggle}
        aria-label="Toggle context panel"
        aria-expanded={open}
        className="absolute top-14 right-2 z-10 text-text-muted hover:text-text px-2 py-1 rounded bg-surface border border-border"
      >
        {open ? "›" : "‹"}
      </button>
      {open && (
        <aside className="w-72 shrink-0 border-l border-border bg-surface p-4 overflow-y-auto">
          <h2 className="font-mono text-sm text-text-muted mb-3">Context</h2>
          <p className="text-text-muted text-sm">
            Turn reasoning, confidence, tool calls, and voice state appear here during a turn.
          </p>
        </aside>
      )}
    </>
  );
}
