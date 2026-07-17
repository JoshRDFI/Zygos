import { Link } from "react-router-dom";

export default function Header() {
  return (
    <header className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-border bg-surface">
      <Link to="/" className="font-mono font-semibold tracking-tight text-text">Zygos</Link>
      <Link to="/settings" aria-label="Settings" title="Settings" className="text-text-muted hover:text-text">
        <span aria-hidden className="text-lg">⚙</span>
      </Link>
    </header>
  );
}
