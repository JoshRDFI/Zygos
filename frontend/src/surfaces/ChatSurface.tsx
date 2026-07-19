import { useState } from "react";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore, getSessionClient } from "../session/sessionStore";
import VoiceControls from "../components/VoiceControls";

export default function ChatSurface() {
  const messages = useChatStore((s) => s.messages);
  const addUser = useChatStore((s) => s.addUser);
  const status = useSessionStore((s) => s.status);
  const start = useSessionStore((s) => s.start);
  const [draft, setDraft] = useState("");

  const offline = status === "disconnected" || status === "error";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    const client = getSessionClient();
    if (!client) return; // session still establishing — keep the draft, add nothing
    addUser(text);
    client.send({ channel: "chat", type: "user_message", payload: { text } });
    setDraft("");
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-text" : "text-text-muted"}>
            <span className="font-mono text-xs mr-2 uppercase">{m.role}</span>
            <span>{m.text}{m.streaming ? " ▍" : ""}</span>
          </div>
        ))}
      </div>
      {offline && (
        <div role="status" className="px-3 py-1 text-xs text-text-muted border-t border-border">
          {status === "error" ? (
            <>
              Couldn&apos;t start a session.{" "}
              <button type="button" onClick={() => start()} className="underline text-accent">
                Retry
              </button>
            </>
          ) : (
            "Disconnected — reload to reconnect."
          )}
        </div>
      )}
      <form onSubmit={submit} className="border-t border-border p-3 flex items-center gap-2">
        <VoiceControls />
        <input
          className="flex-1 bg-surface-2 border border-border rounded px-3 py-2 text-text"
          placeholder="Message Zygos…  (drag a file in for one-off context)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button
          type="submit"
          disabled={offline}
          className="px-4 py-2 rounded bg-accent text-accent-fg font-medium disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
