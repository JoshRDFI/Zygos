import { useEffect, useState } from "react";
import { DefaultModelError, getBackends, getModels, resetDefaultModel, setDefaultModel } from "../client/rest";
import type { BackendsView, Check, DefaultView, HardwareSnapshot, ModelEntry, ModelsView, Sourced } from "../client/types";

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

/** `identity.tensor_bytes` as "<n> layers, <x> GB" (layers + other; experts sit inside layers). */
function tensorSummary(v: unknown): string | null {
  if (typeof v !== "object" || v === null) return null;
  const { layers, other } = v as { layers?: unknown; other?: unknown };
  if (typeof layers !== "object" || layers === null || typeof other !== "number") return null;
  const sizes = Object.values(layers as Record<string, unknown>);
  if (!sizes.every((n) => typeof n === "number")) return null;
  const total = (sizes as number[]).reduce((a, b) => a + b, 0) + other;
  return `${sizes.length} layers, ${gb(total)}`;
}

function fieldLine(key: string, s: Sourced): string {
  const summary = key === "identity.tensor_bytes" ? tensorSummary(s.value) : null;
  const value = summary ?? (typeof s.value === "string" ? s.value : JSON.stringify(s.value));
  const source = s.source === "user" ? "your edit" : s.source;
  return [key, value, source, ...(s.at ? [s.at.slice(0, 10)] : [])].join(" · ");
}

function Profile({ fields }: { fields: ModelEntry["fields"] }) {
  const keys = Object.keys(fields).sort();
  if (keys.length === 0) return null;
  return (
    <details className="text-text-muted">
      <summary className="cursor-pointer">profile</summary>
      <ul className="pl-4">
        {keys.map((k) => <li key={k}>{fieldLine(k, fields[k])}</li>)}
      </ul>
    </details>
  );
}

function CheckLine({ label, check }: { label: string; check: Check }) {
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span className="text-text">{label}</span>
      <span className="text-text-muted">{check.detail}</span>
      {!check.ok && <span className="border border-border rounded px-1 text-xs text-accent">problem</span>}
    </li>
  );
}

function NotSetUp({ label }: { label: string }) {
  return (
    <li className="flex flex-wrap items-center gap-2">
      <span className="text-text-muted">{label}: not set up</span>
    </li>
  );
}

function LlamaCppLines({ b }: { b: BackendsView }) {
  const lc = b.settings.llamacpp;
  if (!lc.server_path && !lc.models_dir) return <NotSetUp label="llama.cpp" />;
  return (
    <>
      {lc.server_path ? <CheckLine label="llama.cpp server" check={b.llamacpp.server} /> : <NotSetUp label="llama.cpp server" />}
      {lc.models_dir ? <CheckLine label="llama.cpp models" check={b.llamacpp.models} /> : <NotSetUp label="llama.cpp models" />}
    </>
  );
}

function Backends({ b, error }: { b: BackendsView | null; error: string | null }) {
  return (
    <section aria-label="Backends" className="space-y-1 font-mono text-sm border border-border rounded p-3">
      <h2 className="text-text-muted">Backends</h2>
      {error ? (
        <div className="text-text-muted">Couldn't load backend status: {error}</div>
      ) : !b ? (
        <div className="text-text-muted">Loading…</div>
      ) : (
        <>
          <ul className="space-y-1">
            {b.ollama ? <CheckLine label="Ollama" check={b.ollama} /> : <NotSetUp label="Ollama" />}
            <LlamaCppLines b={b} />
            {b.vllm ? <CheckLine label="vLLM" check={b.vllm.check} /> : <NotSetUp label="vLLM" />}
          </ul>
          {b.restart_required && <div role="status" className="text-accent">Restart Zygos to apply the new addresses.</div>}
        </>
      )}
      <div className="text-text-muted">Change backend settings with zygos personalize backends.</div>
    </section>
  );
}

function LaunchInfo({ m }: { m: ModelEntry }) {
  const ambiguous = m.mmproj_ambiguous ?? [];
  return (
    <>
      {m.launch_text != null && (
        <div className="flex flex-wrap items-center gap-2 text-text-muted">
          <span className="font-mono text-text">{m.launch_text}</span>
          <span>({m.launch_source === "model" ? "own settings" : "default settings"})</span>
          {m.mmproj && <span>+ vision projector</span>}
        </div>
      )}
      {m.launch_error && <div className="text-text-muted">Launch settings problem: {m.launch_error}</div>}
      {ambiguous.length > 0 && (
        <div className="text-text-muted">
          Projector unclear: {ambiguous.join(", ")} — pairing comes with the next phase
        </div>
      )}
    </>
  );
}

type SetDefault = (m: ModelEntry) => void;

function DefaultControl({ m, onSet, busy }: { m: ModelEntry; onSet: SetDefault; busy: boolean }) {
  if (m.is_default) return <span className="border border-border rounded px-1 text-xs text-accent">default</span>;
  if (m.provider === "llamacpp") {
    return <span className="text-text-muted">can answer once Zygos runs llama-server (next phase)</span>;
  }
  // A model Ollama doesn't have would be ignored straight away; an unreachable Ollama stays settable.
  if (m.provider === "ollama" && m.fit_text === "not installed") return null;
  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => onSet(m)}
      className="px-2 rounded border border-border text-xs text-text disabled:opacity-50"
    >
      Set as default
    </button>
  );
}

function Row({ m, onSet, busy }: { m: ModelEntry; onSet: SetDefault; busy: boolean }) {
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
        <DefaultControl m={m} onSet={onSet} busy={busy} />
      </div>
      {m.served_by && <div className="text-text-muted">served by {m.served_by}</div>}
      <LaunchInfo m={m} />
      {m.profile_error && <div className="text-text-muted">{m.profile_error}</div>}
      <Profile fields={m.fields} />
    </li>
  );
}

function Group({ title, models, onSet, busy, sub = false }: { title: string; models: ModelEntry[]; onSet: SetDefault; busy: boolean; sub?: boolean }) {
  const Heading = sub ? "h4" : "h3";
  return (
    <section className="space-y-2">
      <Heading className="font-mono text-text-muted">{title}</Heading>
      <ul className="space-y-3">
        {models.map((m) => <Row key={`${m.provider}/${m.name}`} m={m} onSet={onSet} busy={busy} />)}
      </ul>
    </section>
  );
}

const routeText = (r: { provider: string; model: string }) => `${r.provider}/${r.model}`;

function DefaultLine({ d, busy, onReset }: { d: DefaultView; busy: boolean; onReset: () => void }) {
  return (
    <section aria-label="Default model" className="space-y-1 font-mono text-sm border border-border rounded p-3">
      <div className="flex flex-wrap items-center gap-2">
        {d.route ? (
          <span>{`Default: ${routeText(d.route)} (${d.source === "saved" ? "saved" : "from config"})`}</span>
        ) : (
          <span className="text-text-muted">Default: none</span>
        )}
        {(d.source === "saved" || d.ignored) && (
          <button
            type="button"
            disabled={busy}
            onClick={onReset}
            className="px-2 rounded border border-border text-xs text-text disabled:opacity-50"
          >
            Reset to config default
          </button>
        )}
      </div>
      {d.ignored && (
        <div className="text-text-muted">
          {`Your saved default ${routeText(d.ignored)} isn't used: ${d.reason ?? "unavailable"}.${d.route ? ` Using ${routeText(d.route)}.` : ""}`}
        </div>
      )}
    </section>
  );
}

function ConfirmDialog({ text, onYes, onNo }: { text: string; onYes: () => void; onNo: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-label="Confirm default model"
      className="border border-accent rounded p-3 space-y-2 text-sm bg-surface-2">
      <p>{text}</p>
      <div className="flex gap-2">
        <button type="button" onClick={onYes} className="px-2 py-1 rounded bg-accent text-accent-fg">Use anyway</button>
        <button type="button" onClick={onNo} className="px-2 py-1 rounded border border-border">Cancel</button>
      </div>
    </div>
  );
}

export default function ModelsSurface() {
  const [v, setV] = useState<ModelsView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [b, setB] = useState<BackendsView | null>(null);
  const [bError, setBError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [defaultError, setDefaultError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<{ m: ModelEntry; text: string } | null>(null);
  useEffect(() => {
    getBackends().then(setB).catch((e: unknown) => setBError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => {
    getModels().then(setV).catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // The PUT/DELETE reply is the full GET /models view: replace the page's data with it.
  const apply = async (call: () => Promise<ModelsView>, m?: ModelEntry) => {
    setBusy(true);
    setDefaultError(null);
    try {
      setV(await call());
      setConfirm(null);
    } catch (e) {
      if (e instanceof DefaultModelError && e.needsConfirm && m) {
        setConfirm({ m, text: `${e.detail}. Use ${m.name} as the default anyway?` });
      } else {
        setConfirm(null);
        setDefaultError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  };
  const onSet: SetDefault = (m) => void apply(() => setDefaultModel(m.provider, m.name, false), m);
  const onUseAnyway = () => confirm && void apply(() => setDefaultModel(confirm.m.provider, confirm.m.name, true), confirm.m);

  const local = (v?.models ?? []).filter((m) => m.location === "local" && m.provider !== "vllm" && m.provider !== "llamacpp");
  const llama = (v?.models ?? []).filter((m) => m.location === "local" && m.provider === "llamacpp");
  const vllm = (v?.models ?? []).filter((m) => m.location === "local" && m.provider === "vllm");
  const cloud = (v?.models ?? []).filter((m) => m.location === "cloud");
  const byFamily = (ms: ModelEntry[]) => {
    const g = new Map<string, ModelEntry[]>();
    for (const m of ms) {
      const k = m.family ?? "other";
      g.set(k, [...(g.get(k) ?? []), m]);
    }
    return g;
  };
  const ollamaFamilies = byFamily(local);
  const llamaFamilies = byFamily(llama);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-lg font-mono">Models</h1>
      {error ? (
        <div className="text-text-muted">Couldn't load models: {error}</div>
      ) : !v ? (
        <div className="text-text-muted">Loading…</div>
      ) : (
        <>
          {v.default && <DefaultLine d={v.default} busy={busy} onReset={() => void apply(resetDefaultModel)} />}
          {confirm && <ConfirmDialog text={confirm.text} onYes={onUseAnyway} onNo={() => setConfirm(null)} />}
          {defaultError && <div role="alert" className="border border-border rounded p-3 text-sm">{defaultError}</div>}
          <Hardware hw={v.hardware} />
          <Backends b={b} error={bError} />
          {v.ollama.configured && !v.ollama.reachable && (
            <div role="alert" className="border border-border rounded p-3 text-sm">
              Ollama is unreachable{v.ollama.error ? `: ${v.ollama.error}` : ""}
            </div>
          )}
          {[...ollamaFamilies].map(([family, ms]) => <Group key={`ollama/${family}`} title={family} models={ms} onSet={onSet} busy={busy} />)}
          {llama.length > 0 && (
            <section className="space-y-3">
              <h3 className="font-mono text-text-muted">llama.cpp</h3>
              <div className="pl-3 space-y-3">
                {[...llamaFamilies].map(([family, ms]) => <Group key={`llamacpp/${family}`} title={family} models={ms} onSet={onSet} busy={busy} sub />)}
              </div>
            </section>
          )}
          {vllm.length > 0 && <Group title="vLLM" models={vllm} onSet={onSet} busy={busy} />}
          {cloud.length > 0 && <Group title="cloud" models={cloud} onSet={onSet} busy={busy} />}
        </>
      )}
      <p className="text-text-muted text-sm border border-dashed border-border rounded p-3">
        Downloading models, testing them and model suggestions come in later phases.
      </p>
    </div>
  );
}
