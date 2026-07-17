import { useEffect, useState } from "react";
import { getManifest } from "../client/rest";
import type { Manifest } from "../client/types";

export default function ToolsSurface() {
  const [m, setM] = useState<Manifest | null>(null);
  useEffect(() => { getManifest().then(setM).catch(() => setM(null)); }, []);

  const tools = m?.plugins.filter((p) => p.kind === "tools") ?? [];

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-mono">Tools</h1>
      {!m ? (
        <div className="text-text-muted">Loading…</div>
      ) : tools.length === 0 ? (
        <div className="text-text-muted">No tools registered.</div>
      ) : (
        <ul className="space-y-2 font-mono text-sm">
          {tools.map((t) => (
            <li key={t.name} className="text-text">{t.name} <span className="text-text-muted">· {t.module}</span></li>
          ))}
        </ul>
      )}
    </div>
  );
}
