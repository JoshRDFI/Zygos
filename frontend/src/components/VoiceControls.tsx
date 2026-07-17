import { useVoiceStore } from "../voice/voiceStore";

const BASE = "px-2 py-2 rounded border text-xs";
const ON = "border-accent text-accent";
const OFF = "border-border text-text-muted";
const DISABLED = "border-border text-text-muted opacity-50 cursor-not-allowed";

export default function VoiceControls() {
  const voiceEnabled = useVoiceStore((s) => s.voiceEnabled);
  const micOn = useVoiceStore((s) => s.micOn);
  const speakerOn = useVoiceStore((s) => s.speakerOn);
  const warning = useVoiceStore((s) => s.warning);
  const setVoiceEnabled = useVoiceStore((s) => s.setVoiceEnabled);
  const toggleMic = useVoiceStore((s) => s.toggleMic);
  const toggleSpeaker = useVoiceStore((s) => s.toggleSpeaker);

  const cls = (active: boolean, enabled: boolean) =>
    `${BASE} ${!enabled ? DISABLED : active ? ON : OFF}`;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button" aria-label="Voice" aria-pressed={voiceEnabled}
        onClick={() => setVoiceEnabled(!voiceEnabled)}
        className={cls(voiceEnabled, true)}
      >
        Voice
      </button>
      <button
        type="button" aria-label="Mic" aria-pressed={micOn} disabled={!voiceEnabled}
        onClick={toggleMic}
        className={cls(micOn, voiceEnabled)}
      >
        Mic
      </button>
      <button
        type="button" aria-label="Always-on" disabled
        title="Continuous listening — coming in increment 1c"
        className={`${BASE} ${DISABLED}`}
      >
        Always-on
      </button>
      <button
        type="button" aria-label="Speaker" aria-pressed={speakerOn} disabled={!voiceEnabled}
        onClick={toggleSpeaker}
        className={cls(speakerOn, voiceEnabled)}
      >
        Speaker
      </button>
      {warning && (
        <span role="status" className="text-xs text-text-muted ml-1">
          {warning}
        </span>
      )}
    </div>
  );
}
