import { useState } from "react";
import { removeServer, setServerOn, setServerTrust, setTimeout_ } from "../../client/mcp";
import type { ServerView } from "../../client/types";
import { useMcpStore } from "../../stores/mcpStore";
import Feedback from "./Feedback";
import SecretRow from "./SecretRow";
import ToolRow from "./ToolRow";
import { BTN } from "./styles";

export default function ServerCard({ server: s }: { server: ServerView }) {
  const busy = useMcpStore((st) => st.busy);
  const run = useMcpStore((st) => st.run);
  const [stderr, setStderr] = useState(false);
  const [editing, setEditing] = useState(false);
  const [timeout, setTimeoutText] = useState(String(s.timeout_s));
  const [removing, setRemoving] = useState(false);
  const off = busy !== null;
  const k = (what: string) => `server:${s.name}:${what}`;
  const secretNames = Object.keys(s.secrets);
  const toolsOn = s.tools.filter((t) => t.on).length;

  const saveTimeout = async () => {
    await run(k("timeout"), () => setTimeout_(s.name, Number(timeout)));
    if (!useMcpStore.getState().errors[k("timeout")]) setEditing(false);
  };

  return (
    <div className="border border-border rounded p-3 space-y-2 text-sm">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono font-semibold">{s.name}</span>
        <span className="text-text-muted font-mono">{s.local ? "local" : "remote"} · {s.runs}</span>
        <span className="ml-auto text-text-muted">
          <span aria-hidden>● </span><span>{s.on ? s.status_word : "off"}</span>
        </span>
      </div>
      {s.on && s.detail && <div className="text-text-muted text-xs">{s.detail}</div>}
      {s.on && s.exit_code !== null && <div className="text-text-muted text-xs">exit code {s.exit_code}</div>}
      {s.stderr_tail && (
        <div className="text-xs">
          <button type="button" className={BTN} aria-expanded={stderr} onClick={() => setStderr((v) => !v)}>
            {stderr ? "stderr ▾" : "stderr ▸"}
          </button>
          {stderr && <pre className="whitespace-pre-wrap break-words font-mono mt-1">{s.stderr_tail}</pre>}
        </div>
      )}

      <div className="flex items-center gap-3 flex-wrap text-xs text-text-muted">
        <span>{s.era ? `protocol ${s.era}` : "protocol not known yet"}</span>
        {editing ? (
          <span className="flex items-center gap-1">
            <input
              type="number" aria-label="Timeout seconds" value={timeout}
              className="w-20 px-2 py-1 rounded border border-border bg-surface font-mono"
              onChange={(e) => setTimeoutText(e.target.value)}
            />
            <button type="button" className={BTN} disabled={off} onClick={saveTimeout}>Save timeout</button>
            <button type="button" className={BTN} disabled={off} onClick={() => { setEditing(false); setTimeoutText(String(s.timeout_s)); }}>
              Cancel
            </button>
          </span>
        ) : (
          <span>
            timeout {s.timeout_s} s{" "}
            <button type="button" className={BTN} disabled={off} aria-label="edit timeout" onClick={() => setEditing(true)}>
              edit
            </button>
          </span>
        )}
        <label className="flex items-center gap-1">
          <input
            type="checkbox" aria-label={`${s.name} on`} checked={s.on} disabled={off}
            onChange={() => run(k("on"), () => setServerOn(s.name, !s.on))}
          />
          on
        </label>
        <label className="flex items-center gap-1">
          <input
            type="checkbox" aria-label={`trust ${s.name}`} checked={s.trusted_server} disabled={off}
            onChange={() => run(k("trust"), () => setServerTrust(s.name, !s.trusted_server))}
          />
          trust server
        </label>
      </div>
      <Feedback k={k("timeout")} />
      <Feedback k={k("on")} />
      <Feedback k={k("trust")} />

      {secretNames.length > 0 && (
        <div className="space-y-1 text-xs">
          <div className="text-text-muted">secrets</div>
          {secretNames.map((n) => (
            <SecretRow key={n} server={s.name} name={n} presence={s.secrets[n]} reason={s.secret_reasons[n]} />
          ))}
          {s.secrets_note && <div className="text-text-muted">{s.secrets_note}</div>}
        </div>
      )}

      {s.tools.length > 0 && (
        <div className="space-y-1 text-xs">
          <div className="text-text-muted">tools ({toolsOn} on of {s.tools.length})</div>
          <ul className="space-y-1">
            {s.tools.map((t) => <ToolRow key={t.server_tool} server={s.name} tool={t} greyed={!s.on} />)}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-2 text-xs">
        {removing ? (
          <>
            <span>{`Remove ${s.name}?`}</span>
            <button
              type="button" className={BTN} disabled={off}
              onClick={async () => { await run(k("remove"), () => removeServer(s.name)); setRemoving(false); }}
            >Confirm remove</button>
            <button type="button" className={BTN} disabled={off} onClick={() => setRemoving(false)}>Cancel</button>
          </>
        ) : (
          <button type="button" className={BTN} disabled={off} onClick={() => setRemoving(true)}>Remove</button>
        )}
      </div>
      <Feedback k={k("remove")} />
    </div>
  );
}
