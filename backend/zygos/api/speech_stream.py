"""Decides when a streamed reply may start being spoken (sentence-streaming speech).

SpeechPacer is pure: no I/O, no asyncio. It is fed streamed text and releases complete
sentences for synthesis only once speech can start without running dry mid-reply: the
words spoken before the writer catches up must cover the time the remaining (assumed)
words will take to arrive at the measured writing rate.

Stability: Experimental.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable

from zygos.api.duck import clear_duck_state
from zygos.api.frames import AUDIO_OUT, Frame
from zygos.runtime.events import SpeechTiming

logger = logging.getLogger("zygos.api.speech_stream")

SPEAKING_RATE_WPS = 3.0
ASSUMED_REPLY_WORDS = 200
START_MARGIN_S = 1.0
MIN_START_WORDS = 8

_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n")


def _words(sentences: list[str]) -> int:
    return sum(len(s.split()) for s in sentences)


class SpeechPacer:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._t0: float | None = None
        self._buf = ""
        self._pending: list[str] = []
        self._started = False
        self._words_at_start: int | None = None
        self._rate_wps: float | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def words_at_start(self) -> int | None:
        return self._words_at_start

    @property
    def rate_wps(self) -> float | None:
        return self._rate_wps

    def _rate(self, words: int) -> float | None:
        if self._t0 is None:
            return None
        t = self._clock() - self._t0
        return words / t if t > 0 else None

    def _split(self) -> list[str]:
        parts = _BOUNDARY.split(self._buf)
        self._buf = parts[-1]
        return [p.strip() for p in parts[:-1] if p.strip()]

    def feed(self, text: str) -> list[str]:
        if not text:
            return []
        if self._t0 is None and text.strip():
            self._t0 = self._clock()
        self._buf += text
        new = self._split()
        if not new:
            return []
        if self._started:
            return new
        self._pending.extend(new)
        w = _words(self._pending)
        if w < MIN_START_WORDS:
            return []
        r = self._rate(w)
        remaining = max(ASSUMED_REPLY_WORDS - w, 0)
        needed = remaining / r if r is not None else 0.0
        if w / SPEAKING_RATE_WPS + START_MARGIN_S < needed:
            return []
        self._started = True
        self._words_at_start = w
        self._rate_wps = r
        out, self._pending = self._pending, []
        return out

    def _drain(self, sentences: list[str]) -> list[str]:
        out = self._pending + sentences
        self._pending = []
        if not self._started:
            self._words_at_start = _words(out)
            self._rate_wps = self._rate(self._words_at_start)
        return out

    def finish(self) -> list[str]:
        sentences = self._split()
        tail = self._buf.strip()
        self._buf = ""
        if tail:
            sentences.append(tail)
        return self._drain(sentences)

    def flush_complete(self) -> list[str]:
        sentences = self._split()
        self._buf = ""
        return self._drain(sentences)


class StreamingSpeaker:
    """Speaks a reply sentence by sentence as it is released, under one tts.begin/tts.end.

    ``say`` is sync and only queues; a single consumer task synthesizes in order. The
    consumer first awaits ``wait_for`` (e.g. the "Let me think" prefix) before sending
    ``tts.begin``. ``close`` drains and ends; ``abort`` cancels and ends. A synthesis
    failure ends the speech with reason ``error`` and never raises out of close/abort;
    the consumer stops at once (``speaking`` drops, later sentences are dropped) and the
    one ``tts.end`` still goes out at close/abort. Speaker turned off mid-reply stops
    synthesis at the next sentence (reason ``cancelled``).
    """

    def __init__(self, session, voice_service, ctx, turn_id: str, *, turn_started_at: float,
                 wait_for: asyncio.Task | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._session = session
        self._voice = voice_service
        self._ctx = ctx
        self._turn_id = turn_id
        self._turn_started_at = turn_started_at
        self._wait_for = wait_for
        self._clock = clock
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._began = False
        self._ended = False
        self._reason = "complete"
        self._first_audio_ms: int | None = None
        self._projected_end: float | None = None
        self._gaps = 0
        self._gap_s = 0.0
        self._stopped = False  # consumer gave up early (synthesis error / Speaker off)

    def _stop(self, reason: str) -> None:
        self._reason = reason
        self._stopped = True
        self._session.speaking = False  # nothing is playing; don't duck for it
        while not self._queue.empty():
            self._queue.get_nowait()

    def say(self, sentences: list[str]) -> None:
        sentences = [s for s in sentences if s and s.strip()]
        if not sentences or self._stopped:
            return
        for s in sentences:
            self._queue.put_nowait(s)
        if self._task is None:
            self._task = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        if self._wait_for is not None:
            await asyncio.wait([self._wait_for])  # never raises; prefix errors are its own
        if self._ctx.cancelled:
            return
        fmt = self._voice.tts_format
        self._session.enqueue(Frame(channel=AUDIO_OUT, type="tts.begin", payload={
            "sample_rate": fmt.sample_rate,
            "channels": fmt.channels,
            "sample_format": fmt.sample_format,
            "turn_id": self._turn_id,
        }))
        self._began = True
        self._session.speaking = True
        bytes_per_s = fmt.sample_rate * fmt.channels * 2
        while True:
            text = await self._queue.get()
            if text is None or self._ctx.cancelled:
                break
            if not self._session.speak:  # Speaker turned off mid-reply
                self._stop("cancelled")
                break
            synth = None
            first_chunk = True
            try:
                synth = self._voice.synthesize_stream(self._ctx, text)
                async for pcm in synth.chunks():
                    if self._ctx.cancelled:
                        break
                    self._track(len(pcm) / bytes_per_s, first_chunk)
                    first_chunk = False
                    self._session.enqueue_audio(pcm)
            except Exception:  # noqa: BLE001 - a synthesis failure must not kill the turn
                self._reason = "error"
                logger.warning("synthesis failed", exc_info=True)
            finally:
                if synth is not None:
                    try:
                        await synth.cancel()
                        await synth.aclose()
                    except Exception:  # noqa: BLE001 - teardown failure must not skip tts.end
                        logger.debug("StreamingSpeaker: synth teardown failed", exc_info=True)
            if self._reason == "error":
                self._stop("error")
                break

    def _track(self, duration: float, first_of_sentence: bool) -> None:
        now = self._clock()
        if self._first_audio_ms is None:
            self._first_audio_ms = round((now - self._turn_started_at) * 1000)
        if self._projected_end is None:
            self._projected_end = now
        elif first_of_sentence and now > self._projected_end:
            self._gaps += 1
            self._gap_s += now - self._projected_end
            self._projected_end = now
        self._projected_end += duration

    async def _end(self, pacer: SpeechPacer, reason: str) -> None:
        if self._ended or not self._began:
            self._ended = True
            return
        self._ended = True
        self._session.speaking = False
        clear_duck_state(self._session)
        self._session.enqueue(Frame(channel=AUDIO_OUT, type="tts.end",
                                    payload={"turn_id": self._turn_id, "reason": reason}))
        rate = pacer.rate_wps
        await self._ctx.emit(
            SpeechTiming(turn_id=self._turn_id, first_audio_ms=self._first_audio_ms,
                         words_at_start=pacer.words_at_start,
                         rate_wps=None if rate is None else round(rate, 1),
                         gaps=self._gaps, gap_ms=round(self._gap_s * 1000), reason=reason),
            source="speech",
        )

    async def close(self, pacer: SpeechPacer) -> None:
        if self._ended or self._task is None:
            return
        self._queue.put_nowait(None)
        await self._task
        reason = self._reason
        if reason != "error" and self._ctx.cancelled:
            reason = "cancelled"
        await self._end(pacer, reason)

    async def abort(self, pacer: SpeechPacer | None = None) -> None:
        if self._ended:
            return
        me = asyncio.current_task()
        before = me.cancelling() if me is not None else 0
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._end(pacer or SpeechPacer(),
                        "error" if self._reason == "error" else "cancelled")
        if me is not None and me.cancelling() > before:
            raise asyncio.CancelledError  # the caller was cancelled while we waited
