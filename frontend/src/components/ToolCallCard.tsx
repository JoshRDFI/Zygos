import { useState } from "react";
import type { Frame, ToolCard } from "../client/types";
import PermissionCard, { OUTCOME } from "./PermissionCard";

const CLIP = 2000;

function text(v: unknown): string {
  if (typeof v === "string") return v;
  try { return JSON.stringify(v, null, 2) ?? String(v); } catch { return String(v); }
}

function argsLine(args: Record<string, unknown>): string {
  let s: string;
  try { s = JSON.stringify(args); } catch { s = "{…}"; }
  return s.length > 80 ? `${s.slice(0, 79)}…` : s;
}

function status(c: ToolCard): string {
  switch (c.status) {
    case "running": return "running…";
    case "done": return "done";
    case "failed": return `failed: ${c.errorMessage ?? ""}`;
    default: return "denied";
  }
}

export default function ToolCallCard({ card, send }: { card: ToolCard; send?: (f: Frame) => void }) {
  const [open, setOpen] = useState(false);
  const [all, setAll] = useState(false);
  if (card.status === "asking") return <PermissionCard card={card} send={send ?? (() => {})} />;

  const hasOutput = card.output !== undefined;
  const body = hasOutput ? text(card.output) : "";
  const clipped = !all && body.length > CLIP;

  return (
    <div className="border border-border rounded p-2 text-xs text-text space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono">{card.tool}</span>
        {card.server && <span className="text-text-muted">{card.server}</span>}
        <span className="font-mono text-text-muted truncate">{argsLine(card.args)}</span>
        <span className="ml-auto text-text-muted">{status(card)}</span>
        {hasOutput && (
          <button type="button" className="px-1 rounded border border-border" onClick={() => setOpen((v) => !v)}>
            {open ? "output ▾" : "output ▸"}
          </button>
        )}
      </div>
      {card.outcome && <div className="text-text-muted">{OUTCOME[card.outcome]}</div>}
      {open && hasOutput && (
        <>
          <pre className="whitespace-pre-wrap break-words font-mono">{clipped ? `${body.slice(0, CLIP)}…` : body}</pre>
          {clipped && (
            <button type="button" className="px-1 rounded border border-border" onClick={() => setAll(true)}>show all</button>
          )}
        </>
      )}
    </div>
  );
}
