import { useThinkStore } from "../stores/thinkStore";
import { useSessionStore, getSessionClient } from "../session/sessionStore";

const BASE = "px-2 py-2 rounded border text-xs";
const ON = "border-accent text-accent";
const OFF = "border-border text-text-muted";
const DISABLED = "border-border text-text-muted opacity-50 cursor-not-allowed";

export default function ThinkControls() {
  const enabled = useThinkStore((s) => s.enabled);
  const supported = useThinkStore((s) => s.supported);
  const reason = useThinkStore((s) => s.reason);
  const voiceNotice = useThinkStore((s) => s.voiceNotice);
  const online = useSessionStore((s) => s.status === "connected");
  const usable = online && supported;

  const toggle = () => {
    getSessionClient()?.send({ channel: "control", type: "think", payload: { enabled: !enabled } });
  };

  return (
    <div className="flex items-center gap-1">
      <button
        type="button" aria-label="Think" aria-pressed={enabled} disabled={!usable}
        title={!supported ? reason ?? undefined : undefined}
        onClick={toggle}
        className={`${BASE} ${!usable ? DISABLED : enabled ? ON : OFF}`}
      >
        Think
      </button>
      {voiceNotice && (
        <span role="status" className="text-xs text-text-muted ml-1">{voiceNotice}</span>
      )}
    </div>
  );
}
