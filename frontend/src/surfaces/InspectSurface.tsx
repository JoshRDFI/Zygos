import { useEffect, useState } from "react";
import { getManifest } from "../client/rest";
import type { Manifest } from "../client/types";

export default function InspectSurface() {
  const [m, setM] = useState<Manifest | null>(null);
  const [err, setErr] = useState<string | null>(null);

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
    </div>
  );
}
