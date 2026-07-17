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

## Status (increment 1b)

Live: Chat (streaming), Inspect, Doctor, Models/Tools lists, and the **voice
audio round-trip** — Mic (click-to-toggle capture → STT), Speaker (TTS
playback), and a Voice master toggle. Placeholder: Files, Memory, model
selection, and the **Always-on** control (browser VAD + duck-then-stop
barge-in are increment 1c).

## Voice round-trip smoke test (increment 1b)

Automated tests cover the pure logic (Vitest/jsdom has no Web Audio); the live
round-trip is a manual check:

1. **Backend with real engines.** From `backend/`: `.venv/bin/python -m pip
   install '.[voice]'`, then run `serve` with config
   `voice.enabled=true`, `voice.stt.engine=faster_whisper`,
   `voice.tts.engine=kokoro` (first run downloads the models). Fake engines
   (`voice.stt.engine=fake` / `voice.tts.engine=fake`) exercise the same
   pipeline with a canned transcript and silent PCM if you only want to test
   the plumbing.
2. **Frontend.** `cd frontend && npm run dev`; open `http://localhost:5173`.
3. **Round-trip.** Click **Voice** (master on) → Mic and Speaker enable. Click
   **Speaker** on. Click **Mic**, speak a sentence, click **Mic** again to
   commit → the transcript appears as a user message and drives a reply; with
   Speaker on you hear Kokoro speak the reply back.
4. **Gate.** Open a second browser tab, toggle **Mic** → the first session owns
   voice, so the second shows the "voice in use" warning and auto-reverts.
5. **Default-off.** With `voice.enabled` unset the backend is unchanged and the
   voice controls send nothing.
