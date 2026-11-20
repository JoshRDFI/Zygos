import { useState } from "react";
import { setSecret } from "../../client/mcp";
import type { SecretPresence } from "../../client/types";
import { useMcpStore } from "../../stores/mcpStore";
import Feedback from "./Feedback";
import { BTN } from "./styles";

interface Props { server: string; name: string; presence: SecretPresence; reason?: string }

export default function SecretRow({ server, name, presence, reason }: Props) {
  const busy = useMcpStore((s) => s.busy);
  const run = useMcpStore((s) => s.run);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const key = `server:${server}:secret:${name}`;

  const save = async () => {
    await run(key, async () => setSecret(server, name, value));
    if (!useMcpStore.getState().errors[key]) {
      setValue("");
      setOpen(false);
    }
  };

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono">{name}</span>
        <span className="text-text-muted">= {presence}{presence === "unknown" && reason ? ` (${reason})` : ""}</span>
        {!open && (
          <button type="button" className={BTN} disabled={busy !== null} onClick={() => setOpen(true)}>
            replace
          </button>
        )}
      </div>
      {open && (
        <div className="flex items-center gap-2 flex-wrap">
          <input
            type="password" autoComplete="off" aria-label={`${name} value`}
            className="px-2 py-1 rounded border border-border bg-surface text-xs font-mono"
            value={value} onChange={(e) => setValue(e.target.value)}
          />
          <button type="button" className={BTN} disabled={busy !== null || value === ""} onClick={save}>Save</button>
          <button
            type="button" className={BTN} disabled={busy !== null}
            onClick={() => { setValue(""); setOpen(false); }}
          >Cancel</button>
        </div>
      )}
      <Feedback k={key} />
    </div>
  );
}
