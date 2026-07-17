const CONTROLS = ["Mic", "Always-on", "Voice", "Speaker"];

export default function VoiceControls() {
  return (
    <div className="flex items-center gap-1">
      {CONTROLS.map((name) => (
        <button
          key={name}
          type="button"
          disabled
          aria-label={name}
          title="Voice — coming in the next increment"
          className="px-2 py-2 rounded border border-border text-text-muted opacity-50 cursor-not-allowed text-xs"
        >
          {name}
        </button>
      ))}
    </div>
  );
}
