import { useEffect, useState } from "react";
import { getModels } from "../client/rest";
import type { HardwareSnapshot, ModelEntry, ModelsView } from "../client/types";

const GB = 1024 ** 3;
const gb = (n: number) => `${(n / GB).toFixed(1)} GB`;
const orUnknown = (n: number | null, f: (n: number) => string = gb) => (n === null ? "unknown" : f(n));

function Hardware({ hw }: { hw: HardwareSnapshot | null }) {
  if (!hw) return <p className="text-text-muted text-sm">Hardware: unknown</p>;
  const gpus = hw.gpus;
  return (
    <section aria-label="Hardware" className="space-y-1 font-mono text-sm border border-border rounded p-3">
      <h2 className="text-text-muted">Hardware</h2>
      {gpus === null || gpus.length === 0 ? (
        <div>GPU: unknown</div>
      ) : (
        <div>
          GPU: {gpus.map((g) => g.name).join(", ")} · VRAM free / total:{" "}
          {(gpus.reduce((n, g) => n + g.vram_free_bytes, 0) / GB).toFixed(1)} /{" "}
          {gb(gpus.reduce((n, g) => n + g.vram_total_bytes, 0))}
        </div>
      )}
      <div>RAM available / total: {orUnknown(hw.ram_available_bytes)} / {orUnknown(hw.ram_total_bytes)}</div>
      <div>CPU: {hw.cpu_model ?? "unknown"}{hw.cpu_cores !== null ? ` (${hw.cpu_cores} threads)` : ""}</div>
      <div>Disk free: {orUnknown(hw.disk_free_bytes)}</div>
    </section>
  );
}

function Row({ m }: { m: ModelEntry }) {
  const caps = Object.entries(m.capabilities).filter(([, v]) => v).map(([k]) => k);
  const chip = "border border-border rounded px-1 text-xs text-text-muted";
  return (
    <li className="font-mono text-sm space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-text">{m.provider} / {m.name}</span>
        {m.download_size_bytes !== null && <span className="text-text-muted">{gb(m.download_size_bytes)}</span>}
        {m.quantization && <span className="text-text-muted">{m.quantization}</span>}
        {m.specialty.map((s) => <span key={s} className={chip}>{s}</span>)}
        {caps.map((c) => <span key={c} className={chip}>{c}</span>)}
        {m.loaded && (
          <span className="text-accent">loaded{m.vram_bytes !== null ? ` · ${gb(m.vram_bytes)} VRAM` : ""}</span>
        )}
        {m.primary && <span className="text-accent">primary</span>}
        {m.fallback && <span className="text-text-muted">fallback</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-text-muted">
        {m.fit && <span className="border border-border rounded px-1 text-text">{m.fit.level}</span>}
        {m.fit_text && <span>{m.fit_text}</span>}
      </div>
      {m.profile_error && <div className="text-text-muted">profile file can't be read: {m.profile_error}</div>}
    </li>
  );
}

function Group({ title, models }: { title: string; models: ModelEntry[] }) {
  return (
    <section className="space-y-2">
      <h3 className="font-mono text-text-muted">{title}</h3>
      <ul className="space-y-3">
        {models.map((m) => <Row key={`${m.provider}/${m.name}`} m={m} />)}
      </ul>
    </section>
  );
}

export default function ModelsSurface() {
  const [v, setV] = useState<ModelsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getModels().then(setV).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const local = (v?.models ?? []).filter((m) => m.location === "local");
  const cloud = (v?.models ?? []).filter((m) => m.location === "cloud");
  const families = new Map<string, ModelEntry[]>();
  for (const m of local) {
    const k = m.family ?? "other";
    families.set(k, [...(families.get(k) ?? []), m]);
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-lg font-mono">Models</h1>
      {error ? (
        <div className="text-text-muted">Couldn't load models: {error}</div>
      ) : !v ? (
        <div className="text-text-muted">Loading…</div>
      ) : (
        <>
          <Hardware hw={v.hardware} />
          {v.ollama.configured && !v.ollama.reachable && (
            <div role="alert" className="border border-border rounded p-3 text-sm">
              Ollama is unreachable{v.ollama.error ? `: ${v.ollama.error}` : ""}
            </div>
          )}
          {[...families].map(([family, ms]) => <Group key={family} title={family} models={ms} />)}
          {cloud.length > 0 && <Group title="cloud" models={cloud} />}
        </>
      )}
      <p className="text-text-muted text-sm border border-dashed border-border rounded p-3">
        Choosing a default model and downloading models come next.
      </p>
    </div>
  );
}
