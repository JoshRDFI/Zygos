import { useEffect, useRef, useState } from "react";
import { useThinkStore } from "../stores/thinkStore";
import { getManifest } from "../client/rest";
import type { Manifest } from "../client/types";

export default function InspectSurface() {
  const [m, setM] = useState<Manifest | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const eventsByTurn = useThinkStore((st) => st.eventsByTurn);
  const turnOrder = useThinkStore((st) => st.turnOrder);
  const selectedTurnId = useThinkStore((st) => st.selectedTurnId);
  const selectedRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    selectedRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [selectedTurnId, turnOrder, m]);

  useEffect(() => {
    getManifest().then(setM).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="p-6 text-text-muted">Failed to load manifest: {err}</div>;
  if (!m) return <div className="p-6 text-text-muted">Loading manifest…</div>;

  return (
    <div className="p-6 space-y-6 font-mono text-sm">
      <h1 className="text-lg">Inspect</h1>
      <section>
        <div>lifecycle: <span className="text-accent">{m.lifecycle_stage}</span></div>
        <div>primary route: {m.primary_route.provider} / {m.primary_route.model}</div>
        <div>reasoning: {String(m.reasoning_enabled)}</div>
        {m.thinking && (
          <div>
            {m.thinking.supported
              ? "thinking: supported"
              : `thinking: unavailable — ${m.thinking.reason ?? "unknown"}`}
          </div>
        )}
        <div>versions: {Object.entries(m.versions).map(([k, v]) => `${k} ${v}`).join("  ")}</div>
      </section>
      <section>
        <h2 className="text-text-muted mb-1">plugins</h2>
        <ul className="space-y-1">
          {m.plugins.map((p) => (
            <li key={`${p.kind}/${p.name}`}>{p.kind} · {p.name} · {p.module}</li>
          ))}
        </ul>
      </section>
      <section>
        <h2 className="text-text-muted mb-1">thinking</h2>
        {turnOrder.length === 0 ? (
          <div className="text-text-muted">No thinking recorded yet.</div>
        ) : (
          <div className="space-y-3">
            {turnOrder.map((tid) => {
              const selected = tid === selectedTurnId;
              return (
                <div
                  key={tid}
                  ref={selected ? selectedRef : undefined}
                  aria-current={selected ? "true" : undefined}
                  className={`border rounded p-2 ${selected ? "border-accent" : "border-border"}`}
                >
                  {(eventsByTurn[tid] ?? []).map((e, i) => (
                    <div key={i} className="mb-2">
                      <div className="text-xs text-text-muted">{`${e.step} #${e.index} · ${e.elapsedMs} ms`}</div>
                      {e.truncated && (
                        <div className="text-xs text-text-muted">{`… ${e.chars - e.text.length} earlier characters not kept`}</div>
                      )}
                      <pre className="whitespace-pre-wrap">{e.text}</pre>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
