import { useEffect, useState } from "react";
import type { Frame, PermissionOutcome, ToolCard } from "../client/types";

const OUTCOME: Record<PermissionOutcome, string> = {
  allowed: "Allowed",
  trusted_tool: "Trusted this tool",
  trusted_server: "Trusted this server",
  denied: "Denied",
  timed_out: "Timed out — denied",
  cancelled: "Cancelled",
  trust_failed: "Allowed — couldn't save trust — it will ask again",
};

const BTN = "px-2 py-1 rounded border border-border text-xs disabled:opacity-50 disabled:cursor-not-allowed";

function pretty(v: unknown): string {
  try { return JSON.stringify(v, null, 2) ?? String(v); } catch { return String(v); }
}

function clock(ms: number): string {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function PermissionCard({ card, send }: { card: ToolCard; send: (f: Frame) => void }) {
  const p = card.permission;
  const deadline = p ? p.askedAt + p.expiresInS * 1000 : 0;
  const [now, setNow] = useState(() => Date.now());
  const [answered, setAnswered] = useState(false);
  const [showSchema, setShowSchema] = useState(false);
  const open = !card.outcome && card.status === "asking";
  const remaining = deadline - now;
  const expired = open && remaining <= 0;

  useEffect(() => {
    if (!open || !p) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [open, p]);

  if (!p) return null;

  const answer = (decision: "allow" | "deny", trust?: "tool" | "server") => {
    if (answered || expired) return;
    setAnswered(true);
    send({
      channel: "tools", type: "permission_response",
      payload: { call_id: card.callId, decision, ...(trust ? { trust } : {}) },
    });
  };
  const off = answered || expired;

  return (
    <div className="border border-border rounded p-2 text-xs text-text space-y-1">
      <div className="font-mono">
        {`${p.server ?? card.server ?? ""} · ${p.serverTool ?? card.tool}`}
        {p.where && p.address && <span className="text-text-muted">{` (${p.where} · ${p.address})`}</span>}
      </div>
      {p.claims.length > 0 && <div className="text-text-muted">{`server says: ${p.claims.join(", ")}`}</div>}
      <div className="text-text-muted">wants to run with:</div>
      <pre className="whitespace-pre-wrap break-words font-mono">{pretty(p.argsSummary)}</pre>
      {p.ruleNote && <div className="text-text-muted">{p.ruleNote}</div>}
      {p.changed && (
        <div className="border border-border rounded p-1 space-y-1">
          <div className="font-semibold">changed since you trusted it</div>
          <div>{`was: ${p.changed.oldDescription}`}</div>
          <div>{`now: ${p.changed.newDescription}`}</div>
          <button type="button" className={BTN} onClick={() => setShowSchema((v) => !v)}>
            {showSchema ? "hide schema" : "show schema"}
          </button>
          {showSchema && (
            <div className="grid grid-cols-2 gap-2">
              <pre className="whitespace-pre-wrap break-words font-mono">{pretty(p.changed.oldSchema)}</pre>
              <pre className="whitespace-pre-wrap break-words font-mono">{pretty(p.changed.newSchema)}</pre>
            </div>
          )}
        </div>
      )}
      {open ? (
        <div className="flex items-center gap-2 flex-wrap">
          <button type="button" className={BTN} disabled={off} onClick={() => answer("allow")}>Allow once</button>
          <button type="button" className={BTN} disabled={off} onClick={() => answer("deny")}>Deny</button>
          {p.canTrust && (
            <>
              <button type="button" className={BTN} disabled={off} onClick={() => answer("allow", "tool")}>Trust this tool</button>
              <button type="button" className={BTN} disabled={off} onClick={() => answer("allow", "server")}>Trust this server</button>
            </>
          )}
          <span className="ml-auto text-text-muted">{expired ? "Timed out" : clock(remaining)}</span>
        </div>
      ) : (
        card.outcome && <div className="text-text-muted">{OUTCOME[card.outcome]}</div>
      )}
    </div>
  );
}
