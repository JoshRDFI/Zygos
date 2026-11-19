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

- **Tests** covered disconnect cleanup of the audio tasks, but none checked that the
  STT request itself was cancelled, and the only one that crossed a session boundary
  (`test_disconnect_releases_voice_for_next_session`) disconnected before any audio was in
  flight. That combination was the only way to see the bug.
- **Reviews** read the teardown as complete: cancelling the tasks looked like cleanup.
  Nothing showed that the sidecar held per-utterance state outside those tasks.
- **Manual testing** mostly used one session per backend start, which never triggers it.
- A plausible wrong theory (the audio worklet failing to load from a data URI) was
  chased first; it was disproved by running the real code path in a headless browser.

## The guard that now catches it

- `backend/tests/api/test_voice_ws.py::test_disconnect_mid_utterance_cancels_and_drains_transcription`
  disconnects mid-utterance and asserts the in-flight transcription's cancellation (which does the
  drain) completed.
- The live check that found it used a headless browser with a fake microphone
  (Playwright with Chromium's fake-media flags and a WAV file). It is not part of the
  test suite.
- Lesson: any resource shared across sessions (sidecars, pools, caches) needs a
  teardown test that proves its per-request state is released, ideally across a
  session boundary.
