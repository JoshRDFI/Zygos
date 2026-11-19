import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useThinkStore } from "../stores/thinkStore";
import ThinkControls from "../components/ThinkControls";
import { useChatStore } from "../stores/chatStore";
import { useSessionStore, getSessionClient } from "../session/sessionStore";
import VoiceControls from "../components/VoiceControls";
import ToolCallCard from "../components/ToolCallCard";

export default function ChatSurface() {
  const messages = useChatStore((s) => s.messages);
  const addUser = useChatStore((s) => s.addUser);
  const status = useSessionStore((s) => s.status);
  const start = useSessionStore((s) => s.start);
  const addReask = useChatStore((s) => s.addReask);
  const supported = useThinkStore((s) => s.supported);
  const reason = useThinkStore((s) => s.reason);
  const selectTurn = useThinkStore((s) => s.select);
  const navigate = useNavigate();
  const [draft, setDraft] = useState("");
  const anyStreaming = messages.some((m) => m.streaming);

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

  const rethink = (question: string, turnId: string) => {
    const client = getSessionClient();
    if (!client) return;
    addReask(question);
    client.send({
      channel: "chat", type: "user_message",
      payload: { text: question, think: true, rethink_of: turnId },
    });
  };

  const openThinking = (turnId: string) => {
    selectTurn(turnId);
    navigate("/inspect");
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-text" : "text-text-muted"}>
            <span className="font-mono text-xs mr-2 uppercase">{m.role}</span>
            {m.role === "assistant" && m.tools && m.tools.length > 0 && (
              <div className="space-y-2 my-2">
                {m.tools.map((c) => (
                  <ToolCallCard key={c.callId} card={c} send={(f) => getSessionClient()?.send(f)} />
                ))}
              </div>
            )}
            <span>{m.text}{m.streaming ? " ▍" : ""}</span>
            {m.role === "assistant" && m.rethinkOf != null && m.think === true && (
              <span className="ml-2 text-xs text-text-muted">with thinking</span>
            )}
            {m.role === "assistant" && m.thinkUnsupportedReason && (
              <span className="ml-2 text-xs text-text-muted">
                {`thinking unavailable — ${m.thinkUnsupportedReason}`}
              </span>
            )}
            {m.role === "assistant" && m.streaming && m.loadingModel && (
              <span className="ml-2 text-xs text-text-muted">{`loading ${m.loadingModel}…`}</span>
            )}
            {m.role === "assistant" && !m.streaming && m.answeredBy && (
              <span className="ml-2 text-xs text-text-muted">{`answered by ${m.answeredBy}`}</span>
            )}
            {m.role === "assistant" && m.streaming && m.think === true && (
              <span className="ml-2 text-xs text-text-muted">Thinking…</span>
            )}
            {m.role === "assistant" && !m.streaming && m.thinkingMs != null && m.turnId && (
              <button
                type="button"
                onClick={() => openThinking(m.turnId as string)}
                className="ml-2 text-xs underline text-accent"
              >
                {`thought for ${(m.thinkingMs / 1000).toFixed(1)} s`}
              </button>
            )}
            {m.role === "assistant" && !m.streaming && m.think !== true && m.turnId && m.question && (
              <button
                type="button"
                disabled={anyStreaming || !supported}
                title={!supported ? reason ?? undefined : undefined}
                onClick={() => rethink(m.question as string, m.turnId as string)}
                className="ml-2 px-2 py-1 rounded border border-border text-xs text-text-muted disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Think it through
              </button>
            )}
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
        <ThinkControls />
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
