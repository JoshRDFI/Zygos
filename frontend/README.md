# Zygos Frontend (RFC-0011)

Self-hosted React + TypeScript + Vite + Tailwind UI for the Zygos runtime.

## Develop

1. Start the backend: from `backend/`, run `.venv/bin/python -m zygos.cli serve`
   (defaults to `127.0.0.1:8000`).
2. From `frontend/`: `npm install` then `npm run dev`.
3. Open the printed `localhost` URL (default `http://localhost:5173`). Vite
   proxies `/sessions`, `/runtime`, and `/ws` to the backend.

## Test / build

- `npm run test` — Vitest unit/component suite.
- `npm run build` — type-check + production build.

## Status (increment 1a)

Live: Chat (streaming), Inspect, Doctor, Models/Tools lists. Placeholder:
Files, Memory, model selection, and voice controls. The live **voice audio
pipeline** (mic/speaker/VAD/barge-in) is increment 1b.
