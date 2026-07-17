export default function Placeholder({ title, note }: { title: string; note: string }) {
  return (
    <div className="p-6">
      <h1 className="text-lg font-mono">{title}</h1>
      <div
        data-testid="placeholder-marker"
        className="mt-4 inline-block text-xs uppercase tracking-wide text-text-muted border border-dashed border-border rounded px-2 py-1"
      >
        Not yet wired
      </div>
      <p className="text-text-muted mt-4 max-w-prose">{note}</p>
    </div>
  );
}
