# Stale speech transcript after a reconnect (2026-09-26)

## Summary

In live voice use, spoken input sometimes got no answer, or an answer to something said
earlier. Once it started it kept happening. Cause: when the WebSocket closed, the
backend stopped feeding audio but never cancelled the speech-to-text request in flight,
so its result stayed queued on the STT sidecar connection that all sessions share. The
next session read that stale result as its own. Fixed in `0e891b0` (teardown cancels and
drains the transcription) with `8735b78` (a blank transcript no longer starts a turn).

## What happened

- The WebSocket handler's teardown cancelled the audio pusher and consumer tasks but did
  not call `transcription.cancel()`.
- The STT worker finished the abandoned utterance anyway and wrote its final result to
  the shared sidecar connection.
- On the next `audio.start`, the new session's `events()` read that result at once as
  its own final transcript. Its turn closed, its real audio was dropped, and its own
  result was orphaned in turn: a self-perpetuating desync.
- A second detail mattered: the handler task is itself cancelled during teardown, so
  the cancel-and-drain had to run under `asyncio.shield`. Without that, the regression
  test failed about 60% of the time.

## Why every safety net missed it

- **Unit tests** used a fresh fake STT per test, so state could never leak between
  sessions. The bug needed a *shared* sidecar plus a disconnect mid-utterance.
- **Reviews** read the teardown as complete: cancelling the tasks looked like cleanup.
  Nothing showed that the sidecar held per-utterance state outside those tasks.
- **Manual testing** mostly used one session per backend start, which never triggers it.
- A plausible wrong theory (the audio worklet failing to load from a data URI) was
  chased first; it was disproved by running the real code path headless.

## The guard that now catches it

- A regression test drives two sessions against one shared fake sidecar: disconnect
  mid-utterance, reconnect, speak again, and assert the second turn gets its own
  transcript. It fails with the cancel-and-drain removed.
- A headless browser harness with a fake microphone (Playwright with Chromium's
  fake-media flags and a WAV file) reproduces live voice without a person.
- Lesson: any resource shared across sessions (sidecars, pools, caches) needs a
  teardown test that crosses a session boundary.
