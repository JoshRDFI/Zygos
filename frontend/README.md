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
playback), Voice master toggle, and **Always-on** (hands-free with browser VAD
+ duck-then-stop barge-in). Placeholder: Files, Memory, model selection.

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

## Voice barge-in smoke test (increment 1c)

Silero VAD runs as WASM/onnx in a real browser (absent from jsdom), so the live
barge-in path is a manual check. Assets are self-hosted under `public/vad`
(populated by `npm run vendor:vad`, run automatically on install/dev/build).

1. **Backend with real engines** — as in the 1b smoke test: `.[voice]` installed,
   `voice.enabled=true`, `voice.stt.engine=faster_whisper`, `voice.tts.engine=kokoro`.
2. **Frontend** — `npm run dev`; open `http://localhost:5173`. **Use headphones**
   so the assistant's own audio does not re-trigger the mic.
3. **Hands-free turn.** Click **Voice**, then **Speaker**, then **Always-on**
   (Mic disables; "listening…" shows). Speak a sentence and pause → it transcribes
   and drives a reply with no Mic click.
4. **Barge-in.** While the assistant is speaking, talk over it → the reply first
   **ducks** (quieter), then **stops** within a few hundred ms (buffered audio is
   flushed), and your new utterance drives the next reply. This is the first live
   exercise of the `ba6a75fb` drain-to-terminal fix.
5. **False alarm.** A brief cough/noise **ducks** but does **not** stop the
   assistant — it restores to full volume on its own.
6. **Teardown.** Navigate away from Chat and back, or toggle **Voice** off → the
   mic-VAD stops cleanly (no lingering mic indicator).
