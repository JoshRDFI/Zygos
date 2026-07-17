import { useEffect, useState } from "react";
import { getManifest } from "../client/rest";
import type { Manifest } from "../client/types";

export default function ModelsSurface() {
  const [m, setM] = useState<Manifest | null>(null);
  useEffect(() => { getManifest().then(setM).catch(() => setM(null)); }, []);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-lg font-mono">Models</h1>
      {!m ? (
        <div className="text-text-muted">Loading…</div>
      ) : (
        <ul className="space-y-2 font-mono text-sm">
          <li className="text-text">{m.primary_route.provider} / {m.primary_route.model} <span className="text-accent">· primary</span></li>
          {m.fallback_routes.map((r) => (
            <li key={`${r.provider}/${r.model}`} className="text-text-muted">{r.provider} / {r.model} · fallback</li>
          ))}
        </ul>
      )}
      <p className="text-text-muted text-sm border border-dashed border-border rounded p-3">
        Model selection & hardware-aware gating — coming later (RFC-0009 / model-picker).
      </p>
    </div>
  );
}
