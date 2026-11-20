import { useMcpStore } from "../../stores/mcpStore";

/** The refusal and the notes of the last action on one control, shown next to it. */
export default function Feedback({ k }: { k: string }) {
  const error = useMcpStore((s) => s.errors[k]);
  const notes = useMcpStore((s) => s.notes[k]);
  return (
    <>
      {error && <div role="alert" className="text-xs text-text">{error}</div>}
      {notes?.map((n) => <div key={n} className="text-xs text-text-muted">{n}</div>)}
    </>
  );
}
