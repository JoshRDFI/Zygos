import { NavLink } from "react-router-dom";

export const SURFACES: { path: string; label: string }[] = [
  { path: "/", label: "Chat" },
  { path: "/files", label: "Files" },
  { path: "/tools", label: "Tools" },
  { path: "/memory", label: "Memory" },
  { path: "/inspect", label: "Inspect" },
  { path: "/models", label: "Models" },
  { path: "/doctor", label: "Doctor" },
];

export default function LeftRail() {
  return (
    <nav className="w-40 shrink-0 border-r border-border bg-surface p-2 flex flex-col gap-1">
      {SURFACES.map((s) => (
        <NavLink
          key={s.path}
          to={s.path}
          end={s.path === "/"}
          className={({ isActive }) =>
            `px-3 py-2 rounded text-sm ${
              isActive ? "bg-surface-2 text-text" : "text-text-muted hover:text-text hover:bg-surface-2"
            }`
          }
        >
          {s.label}
        </NavLink>
      ))}
    </nav>
  );
}
