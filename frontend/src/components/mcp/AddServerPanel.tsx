import { useRef, useState } from "react";
import { McpError, planAdd, saveServers } from "../../client/mcp";
import type { PlannedServer } from "../../client/types";
import { useMcpStore } from "../../stores/mcpStore";
import Feedback from "./Feedback";
import { BTN } from "./styles";

interface Plan { servers: PlannedServer[]; problems: string[] }

const KEY = "add";

function Preview({ p }: { p: PlannedServer }) {
  return (
    <li className="space-y-1">
      <div className="font-mono">{p.name}</div>
      <div>{p.transport === "stdio" ? `This runs \`${p.runs}\` on this machine as you` : p.runs}</div>
      {p.secret_names.length > 0 && <div className="text-text-muted">{`secrets: ${p.secret_names.join(", ")}`}</div>}
      {p.unused.length > 0 && <div className="text-text-muted">{`unused: ${p.unused.join(", ")}`}</div>}
      {p.replaces && <div>{`replaces the existing ${p.name}${p.old_runs ? ` (\`${p.old_runs}\`)` : ""}`}</div>}
    </li>
  );
}

export default function AddServerPanel({ onDone }: { onDone: () => void }) {
  const busy = useMcpStore((s) => s.busy);
  const run = useMcpStore((s) => s.run);
  const [text, setText] = useState("");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const latest = useRef(0);
  const off = busy !== null || previewing;

  const edit = (v: string) => { latest.current += 1; setText(v); setPlan(null); setPreviewError(null); };

  const preview = async () => {
    const mine = ++latest.current;
    setPreviewing(true);
    setPreviewError(null);
    try {
      const result = await planAdd(text);
      if (mine === latest.current) setPlan(result);
    } catch (e) {
      if (mine !== latest.current) return;
      setPlan(null);
      setPreviewError(e instanceof McpError ? e.detail : e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewing(false);
    }
  };

  const confirm = async () => {
    if (!plan) return;
    const replaces = plan.servers.filter((p) => p.replaces).map((p) => p.name);
    await run(KEY, async () => {
      const r = await saveServers(text, replaces);
      return { view: r.view, notes: [...r.notes, ...r.listing] };
    });
    if (!useMcpStore.getState().errors[KEY]) onDone();
  };

  return (
    <div className="border border-border rounded p-3 space-y-2 text-sm">
      <label className="block text-xs text-text-muted" htmlFor="mcp-add-text">Server JSON</label>
      <textarea
        id="mcp-add-text" rows={6} value={text} disabled={previewing} onChange={(e) => edit(e.target.value)}
        className="w-full px-2 py-1 rounded border border-border bg-surface font-mono text-xs"
      />
      <div className="flex gap-2">
        <button type="button" className={BTN} disabled={off || text.trim() === ""} onClick={preview}>Preview</button>
        <button type="button" className={BTN} disabled={off} onClick={onDone}>Close</button>
      </div>
      {previewError && <div role="alert" className="text-xs">{previewError}</div>}
      {plan && (
        <div className="space-y-2 text-xs">
          <ul className="space-y-2">{plan.servers.map((p) => <Preview key={p.name} p={p} />)}</ul>
          {plan.problems.length > 0 && (
            <ul className="space-y-1">{plan.problems.map((p) => <li key={p} role="alert">{p}</li>)}</ul>
          )}
          <button
            type="button" className={BTN}
            disabled={off || plan.problems.length > 0 || plan.servers.length === 0} onClick={confirm}
          >Confirm</button>
        </div>
      )}
      <Feedback k={KEY} />
    </div>
  );
}
