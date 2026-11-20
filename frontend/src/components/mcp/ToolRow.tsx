import { useState } from "react";
import { setToolOn, setToolTrust } from "../../client/mcp";
import type { ToolView } from "../../client/types";
import { useMcpStore } from "../../stores/mcpStore";
import Feedback from "./Feedback";
import { BTN } from "./styles";

const TRUST_WORD = { trusted: "trusted", asks: "asks", changed: "changed" } as const;
const TRUST_ACTION = { trusted: "untrust", asks: "trust", changed: "trust again" } as const;

export default function ToolRow({ tool, greyed }: { tool: ToolView; greyed: boolean }) {
  const busy = useMcpStore((s) => s.busy);
  const run = useMcpStore((s) => s.run);
  const [open, setOpen] = useState(false);
  const off = busy !== null;
  const onKey = `tool:${tool.zname}:on`;
  const trustKey = `tool:${tool.zname}:trust`;

  return (
    <li className={`space-y-1 ${greyed ? "opacity-50" : ""}`}>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono min-w-[10rem]">{tool.server_tool}</span>
        {tool.problem ? (
          <span className="text-text-muted">{tool.problem}</span>
        ) : (
          <>
            <span className="text-text-muted">{TRUST_WORD[tool.trust]}</span>
            {tool.trust === "changed" && (
              <button type="button" className={BTN} aria-expanded={open} onClick={() => setOpen((v) => !v)}>
                {open ? "hide details" : "show details"}
              </button>
            )}
            <label className="flex items-center gap-1 text-text-muted">
              <input
                type="checkbox" aria-label={`${tool.server_tool} on`} checked={tool.on} disabled={off}
                onChange={() => run(onKey, () => setToolOn(tool.zname, !tool.on))}
              />
              on
            </label>
            <button
              type="button" className={BTN} disabled={off}
              onClick={() => run(trustKey, () => setToolTrust(tool.zname, tool.trust !== "trusted"))}
            >{TRUST_ACTION[tool.trust]}</button>
          </>
        )}
      </div>
      {open && tool.trust === "changed" && (
        <div className="text-xs space-y-1">
          <div>{`was: ${tool.was ?? ""}`}</div>
          <div>{`now: ${tool.now ?? ""}`}</div>
        </div>
      )}
      <Feedback k={onKey} />
      <Feedback k={trustKey} />
    </li>
  );
}
