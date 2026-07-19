import { useEffect, useRef, useState } from "react";
import { getHealth } from "../client/rest";
import type { RuntimeHealth } from "../client/types";

export default function DoctorSurface() {
  const [h, setH] = useState<RuntimeHealth | null>(null);
  const [failed, setFailed] = useState(false);
  const seq = useRef(0);

  const load = (probe: boolean) => {
    const mine = ++seq.current; // ignore results from a superseded request
    getHealth(probe)
      .then((res) => { if (mine === seq.current) { setH(res); setFailed(false); } })
      .catch(() => { if (mine === seq.current) { setH(null); setFailed(true); } });
  };
  useEffect(() => { load(false); }, []);

  return (
    <div className="p-6 space-y-6 font-mono text-sm">
      <div className="flex items-center justify-between">
        <h1 className="text-lg">Doctor</h1>
        <button
          onClick={() => load(true)}
          className="px-3 py-1 rounded border border-border text-text-muted hover:text-text"
        >
          Probe embedder
        </button>
      </div>
      {failed ? (
        <div role="alert" className="text-text-muted">
          Couldn&apos;t load runtime health — check that the backend is running, then probe to retry.
        </div>
      ) : !h ? (
        <div className="text-text-muted">Loading health…</div>
      ) : (
        <>
          <section>
            <h2 className="text-text-muted mb-1">routes</h2>
            <ul>{h.routes.map((r) => (
              <li key={`${r.provider}/${r.model}`}>{r.provider} / {r.model} — {r.circuit}</li>
            ))}</ul>
          </section>
          <div>embedder: {h.embedder.backend} / {h.embedder.model} — <span className="text-accent">{h.embedder.state}</span></div>
          <div>active sessions: {h.active_sessions}</div>
        </>
      )}
    </div>
  );
}
