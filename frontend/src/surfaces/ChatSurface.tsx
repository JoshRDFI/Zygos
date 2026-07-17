import { useEffect, useRef, useState } from "react";
import { createSession } from "../client/rest";
import { WsClient } from "../client/wsClient";
import { useChatStore } from "../stores/chatStore";
import VoiceControls from "../components/VoiceControls";
import { useVoiceStore } from "../voice/voiceStore";

export default function ChatSurface() {
  const messages = useChatStore((s) => s.messages);
  const addUser = useChatStore((s) => s.addUser);
  const onFrame = useChatStore((s) => s.onFrame);
  const [draft, setDraft] = useState("");
  const clientRef = useRef<WsClient | null>(null);

  useEffect(() => {
    let disposed = false;
    let client: WsClient | null = null;
    createSession().then((id) => {
      if (disposed) return;
      client = new WsClient(id);
      for (const t of ["turn.start", "token", "turn.end", "error", "partial", "final"]) {
        client.on(`chat:${t}`, onFrame);
      }
      useVoiceStore.getState().attach(client);
      client.connect();
      clientRef.current = client;
    });
    return () => {
      disposed = true;
      useVoiceStore.getState().detach();
      client?.close();
    };
  }, [onFrame]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    addUser(text);
    clientRef.current?.send({ channel: "chat", type: "user_message", payload: { text } });
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
      <form onSubmit={submit} className="border-t border-border p-3 flex items-center gap-2">
        <VoiceControls />
        <input
          className="flex-1 bg-surface-2 border border-border rounded px-3 py-2 text-text"
          placeholder="Message Zygos…  (drag a file in for one-off context)"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" className="px-4 py-2 rounded bg-accent text-accent-fg font-medium">
          Send
        </button>
      </form>
    </div>
  );
}
