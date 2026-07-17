export default function StubSurface({ name }: { name: string }) {
  return (
    <div className="p-6">
      <h1 className="text-lg font-mono">{name}</h1>
      <p className="text-text-muted mt-2">Surface stub — wired in a later task.</p>
    </div>
  );
}
