import { useEffect, useState } from "react";
import { refreshMcp } from "../../client/mcp";
import { useMcpStore } from "../../stores/mcpStore";
import AddServerPanel from "./AddServerPanel";
import Feedback from "./Feedback";
import ServerCard from "./ServerCard";
import { BTN } from "./styles";

export default function McpSection() {
  const view = useMcpStore((s) => s.view);
  const loadError = useMcpStore((s) => s.loadError);
  const busy = useMcpStore((s) => s.busy);
  const load = useMcpStore((s) => s.load);
  const run = useMcpStore((s) => s.run);
  const notes = useMcpStore((s) => s.notes);
  const [adding, setAdding] = useState(false);

  useEffect(() => { void load(); }, [load]);

  if (!view) return <div className="text-text-muted">{loadError ?? "Loading…"}</div>;
  if (!view.installed) {
    return <div className="text-text-muted">MCP support not installed — pip install -e '.[mcp]'</div>;
  }
  const off = busy !== null;

  return (
    <section className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 className="font-mono">MCP servers</h2>
        <button
          type="button" className={`${BTN} ml-auto`} disabled={off}
          onClick={() => run("refresh", () => refreshMcp())}
        >Refresh</button>
        <button type="button" className={BTN} disabled={off} onClick={() => setAdding((v) => !v)}>+ Add server</button>
      </div>
      <Feedback k="refresh" />
      {view.warning && <div className="text-xs">⚠ {view.warning}</div>}
      {Object.entries(notes).filter(([k]) => k.endsWith(":remove") && !view.servers.some((s) => k === `server:${s.name}:remove`))
        .flatMap(([, ns]) => ns).map((n) => <div key={n} className="text-xs text-text-muted">{n}</div>)}
      {adding && <AddServerPanel onDone={() => setAdding(false)} />}
      {view.servers.length === 0 && !adding && <div className="text-text-muted text-sm">No MCP servers.</div>}
      {view.servers.map((s) => <ServerCard key={s.name} server={s} />)}
    </section>
  );
}
